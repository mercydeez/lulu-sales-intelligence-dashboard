"""
POS intake — the front door for a real retailer's transaction feed.

WHY THIS EXISTS. `identity.ingest_pos_row()` could stage a POS transaction and
`identity.resolve_pending()` could resolve staged rows to customers, but nothing
could CALL the first one: there was no route, so a retailer had no way to hand
over a feed at all. The resolve endpoint sat there with nothing to resolve.

That is the binding constraint on the whole lighthouse pilot — until real
transactions land, there is no audience, no holdout, no incrementality readout
and no causal evidence to graduate a model on.

THE GATE AT THE DOOR. The go-to-market plan rates "real POS data quality poisons
the holdout" a HIGH risk, and it is right: a bad feed does not announce itself,
it quietly produces confident wrong numbers downstream. So every row is checked
before it is staged, and the checking follows two rules:

  1. REJECT THE ROW, NEVER THE BATCH. A real first export always has some bad
     rows. Failing the whole file teaches the integrator nothing and burns a day
     per iteration; accepting it silently poisons every number that follows.
     Each bad row is refused individually WITH ITS REASON and its index, so the
     retailer's engineer can fix exactly what is broken.
  2. A ROW THAT CANNOT BE TRUSTED IS NOT STAGED. Not flagged-and-kept — a
     staged row is indistinguishable from a good one two steps later.

The distinction between a REJECT and a WARN is the same one the data-trust gate
draws: a contradiction (a store that is not yours, an unparseable date, a
negative amount on a positive sale) is refused, while a missing-but-optional
signal (no loyalty identifier — a genuine cash sale) is accepted and noted.

PII: a raw card number is REFUSED, loudly. `card_hash` is meant to be a hash;
a feed that ships PANs is a compliance incident, and accepting one would make us
the party that stored it.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flywheel import identity

logger = logging.getLogger(__name__)

#: One request should not be able to pin the event loop or the database.
MAX_BATCH = 5000
#: Clock skew we forgive on occurred_at before calling a timestamp impossible.
FUTURE_SKEW = timedelta(hours=24)
#: Older than this and the row is almost certainly a parsing error (a mis-read
#: epoch, a two-digit year) rather than a real historical sale.
MAX_AGE_DAYS = 365 * 5
_DIGITS = re.compile(r"^\d{13,19}$")


def _luhn_ok(number: str) -> bool:
    """Luhn check — the cheap test that separates a real card number from an
    arbitrary run of digits, so the PAN refusal does not fire on a numeric id."""
    total, alt = 0, False
    for ch in reversed(number):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def looks_like_card_number(value: Optional[str]) -> bool:
    """True when a field that should hold a HASH holds something shaped like a
    payment card. Digits alone are not enough (a loyalty id is often numeric);
    it must also pass Luhn."""
    if not value:
        return False
    v = re.sub(r"[ -]", "", str(value))
    return bool(_DIGITS.match(v)) and _luhn_ok(v)


def _parse_when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def validate_row(
    row: Dict[str, Any], *, index: int, now: datetime,
    known_stores: Set[int], known_items: Set[int],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pure per-row check. Returns (cleaned_row | None, findings).

    `cleaned_row is None` means the row is refused; findings carry the reasons.
    Findings with severity 'warn' accompany an accepted row.
    """
    findings: List[Dict[str, Any]] = []

    def reject(code: str, detail: str):
        findings.append({"row": index, "severity": "reject", "code": code,
                         "detail": detail,
                         "external_txn_id": str(row.get("external_txn_id") or "")[:120]})
        return None, findings

    def warn(code: str, detail: str) -> None:
        findings.append({"row": index, "severity": "warn", "code": code,
                         "detail": detail,
                         "external_txn_id": str(row.get("external_txn_id") or "")[:120]})

    # --- identity of the transaction itself --------------------------------
    txn_id = row.get("external_txn_id")
    if txn_id is None or not str(txn_id).strip():
        return reject("missing_external_txn_id",
                      "No external_txn_id. Without a stable id from the source "
                      "system, re-importing the same export double-counts every row.")
    txn_id = str(txn_id).strip()
    if len(txn_id) > 120:
        return reject("external_txn_id_too_long",
                      f"external_txn_id is {len(txn_id)} chars (max 120).")

    # --- when ---------------------------------------------------------------
    when = _parse_when(row.get("occurred_at"))
    if when is None:
        return reject("unparseable_occurred_at",
                      f"occurred_at {row.get('occurred_at')!r} is not an ISO-8601 "
                      "timestamp. A sale with no trustworthy time cannot be "
                      "attributed to a campaign window.")
    if when > now + FUTURE_SKEW:
        return reject("occurred_at_in_future",
                      f"occurred_at {when.isoformat()} is in the future.")
    if when < now - timedelta(days=MAX_AGE_DAYS):
        return reject("occurred_at_implausibly_old",
                      f"occurred_at {when.isoformat()} is more than {MAX_AGE_DAYS // 365} "
                      "years old — almost always a date-parsing error.")

    # --- quantity and money -------------------------------------------------
    try:
        units = int(row.get("units", 1))
    except (TypeError, ValueError):
        return reject("units_not_an_integer", f"units {row.get('units')!r} is not an integer.")
    if units == 0:
        return reject("units_zero", "units is 0 — the row records nothing.")
    if abs(units) > 100_000:
        return reject("units_implausible", f"units {units} is implausibly large.")

    raw_amount = row.get("amount_aed", 0)
    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError, ValueError):
        return reject("amount_not_numeric", f"amount_aed {raw_amount!r} is not a number.")
    if not amount.is_finite():
        return reject("amount_not_finite", "amount_aed is not a finite number.")
    # Sign agreement is the cheap check that catches a whole class of feed bugs:
    # returns exported as positive amounts inflate revenue silently.
    if units > 0 and amount < 0:
        return reject("amount_sign_mismatch",
                      f"units {units} is positive but amount_aed {amount} is negative.")
    if units < 0 and amount > 0:
        return reject("amount_sign_mismatch",
                      f"units {units} is a return but amount_aed {amount} is positive.")

    # --- scope: a row must belong to THIS tenant ---------------------------
    store_id = row.get("store_id")
    if store_id is not None:
        try:
            store_id = int(store_id)
        except (TypeError, ValueError):
            return reject("store_not_an_integer", f"store_id {row.get('store_id')!r} is not an integer.")
        if store_id not in known_stores:
            return reject("unknown_store",
                          f"store_id {store_id} is not a store on this tenant.")
    else:
        warn("no_store", "No store_id — the row cannot be attributed to a location.")

    item_id = row.get("item_id")
    if item_id is not None:
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            return reject("item_not_an_integer", f"item_id {row.get('item_id')!r} is not an integer.")
        if item_id not in known_items:
            return reject("unknown_item",
                          f"item_id {item_id} is not an item on this tenant.")
    else:
        warn("no_item", "No item_id — the row cannot inform product-level demand.")

    # --- customer identity + PII refusal -----------------------------------
    loyalty_ref = row.get("loyalty_ref")
    card_hash = row.get("card_hash")
    loyalty_ref = str(loyalty_ref).strip() if loyalty_ref not in (None, "") else None
    card_hash = str(card_hash).strip() if card_hash not in (None, "") else None

    if looks_like_card_number(card_hash):
        return reject("raw_card_number_refused",
                      "card_hash looks like a raw payment card number. Send a hash. "
                      "Accepting this would make us the party storing a PAN.")
    if looks_like_card_number(loyalty_ref):
        return reject("raw_card_number_refused",
                      "loyalty_ref looks like a raw payment card number.")
    if not loyalty_ref and not card_hash:
        # Legitimate — a cash sale by an anonymous shopper is real data. It just
        # can never resolve to a customer, so it is noted rather than refused.
        warn("anonymous_transaction",
             "No loyalty_ref or card_hash — this sale can never resolve to a customer.")

    return {
        "external_txn_id": txn_id, "occurred_at": when, "units": units,
        "amount_aed": amount, "store_id": store_id, "item_id": item_id,
        "loyalty_ref": loyalty_ref, "card_hash": card_hash,
    }, findings


async def _tenant_scope(db: AsyncSession, tenant_id: int,
                        accessible_store_ids: Optional[Sequence[int]]) -> Tuple[Set[int], Set[int]]:
    """The store and item ids this tenant may reference. Fetched once per batch,
    not per row — a 5,000-row file must not become 10,000 queries."""
    store_rows = (await db.execute(
        text("SELECT id FROM stores WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    stores = {int(r[0]) for r in store_rows}
    if accessible_store_ids:
        stores &= {int(s) for s in accessible_store_ids}
    item_rows = (await db.execute(
        text("SELECT id FROM items WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    return stores, {int(r[0]) for r in item_rows}


async def intake_batch(
    db: AsyncSession, *, tenant_id: int, rows: Iterable[Dict[str, Any]],
    accessible_store_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Validate and stage a batch of POS transactions.

    Does not commit — the route owns the transaction, so a caller can wrap the
    intake and anything it triggers in one unit.
    """
    rows = list(rows)
    if not rows:
        raise ValueError("No rows supplied")
    if len(rows) > MAX_BATCH:
        raise ValueError(f"Batch of {len(rows)} exceeds the {MAX_BATCH}-row limit")

    stores, items = await _tenant_scope(db, tenant_id, accessible_store_ids)
    now = datetime.now(timezone.utc)

    findings: List[Dict[str, Any]] = []
    staged = duplicates = rejected = 0

    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            findings.append({"row": i, "severity": "reject", "code": "not_an_object",
                             "detail": "Row is not an object.", "external_txn_id": ""})
            rejected += 1
            continue
        clean, row_findings = validate_row(
            raw, index=i, now=now, known_stores=stores, known_items=items)
        findings.extend(row_findings)
        if clean is None:
            rejected += 1
            continue
        # ingest_pos_row is idempotent on external_txn_id and returns 0 when the
        # row was already staged, which is how a re-sent export is counted as a
        # duplicate rather than silently double-landed.
        new_id = await identity.ingest_pos_row(
            db, tenant_id=tenant_id, external_txn_id=clean["external_txn_id"],
            occurred_at=clean["occurred_at"], loyalty_ref=clean["loyalty_ref"],
            card_hash=clean["card_hash"], store_id=clean["store_id"],
            item_id=clean["item_id"], units=clean["units"],
            amount_aed=clean["amount_aed"])
        if new_id:
            staged += 1
        else:
            duplicates += 1

    accepted = staged + duplicates
    logger.info("flywheel.pos_intake tenant=%s rows=%s staged=%s dup=%s rejected=%s",
                tenant_id, len(rows), staged, duplicates, rejected)
    return {
        "received": len(rows),
        "staged": staged,
        "duplicates": duplicates,
        "rejected": rejected,
        "accepted": accepted,
        # Rejections first: they are what the integrator has to fix.
        "findings": sorted(findings, key=lambda f: (f["severity"] != "reject", f["row"])),
        "reject_codes": sorted({f["code"] for f in findings if f["severity"] == "reject"}),
        "warn_codes": sorted({f["code"] for f in findings if f["severity"] == "warn"}),
        "next_step": ("Nothing staged — fix the rejected rows and re-send."
                      if staged == 0 else
                      "POST /api/flywheel/identity/resolve to link staged rows to customers."),
    }
