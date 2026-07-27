"""Global contact governance — caps belong to the CUSTOMER, not the campaign.

THE BUG THIS FIXES. v1 enforced `contact_cap_per_week` per campaign. Three live
campaigns each capped at 2 could therefore contact the same person six times a
week, each one individually compliant and the aggregate indefensible. The
customer does not experience "campaigns"; they experience messages. So the cap
has to be evaluated across every live campaign and every channel at once.

FOUR GATES, in increasing cost to evaluate:
  1. per-day cap        (cheapest, catches burst sending)
  2. per-channel weekly cap
  3. ALL-CHANNEL weekly ceiling  — the one v1 had no concept of
  4. ignore-cooldown    (someone ignoring offers is telling you something)

CONSENT IS RE-CHECKED AT ISSUE TIME, not at audience build. An audience built on
Monday and executed on Friday must not contact someone who revoked consent on
Wednesday — and revocation is exactly the moment when getting it wrong is most
damaging.

OFFER CONFLICT. When a customer qualifies for several live campaigns, exactly
one may win. The resolution is deterministic (priority, then EIV, then id) and
every loser is RECORDED, because a marketer whose campaign silently stops
reaching people will not trust the system again.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ContactDecision:
    """Why a contact was allowed or refused, in a form the UI can render."""

    def __init__(self, allowed: bool, reason_code: str = "", detail: str = "",
                 counts: Optional[Dict[str, int]] = None):
        self.allowed = allowed
        self.reason_code = reason_code
        self.detail = detail
        self.counts = counts or {}

    def as_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "reason_code": self.reason_code,
                "detail": self.detail, "counts": self.counts}


async def _policy(db: AsyncSession, tenant_id: int,
                  channel: Optional[str]) -> Dict[str, int]:
    """The policy row for a channel, falling back to the all-channel row."""
    row = (await db.execute(
        text("""SELECT max_contacts_per_week, max_contacts_per_day,
                       cooldown_days_after_ignores, ignores_before_cooldown
                  FROM flywheel_contact_policy
                 WHERE tenant_id = :t AND is_active = TRUE
                   AND (channel = :ch OR channel IS NULL)
                 ORDER BY (channel IS NOT NULL) DESC
                 LIMIT 1"""),
        {"t": tenant_id, "ch": channel},
    )).fetchone()
    if not row:
        # No policy configured: permissive but bounded. Refusing everything
        # would break a fresh install; unlimited would be worse.
        return {"week": 3, "day": 1, "cooldown_days": 14, "ignores": 3}
    return {"week": int(row[0]), "day": int(row[1]),
            "cooldown_days": int(row[2]), "ignores": int(row[3])}


async def may_contact(
    db: AsyncSession, *, tenant_id: int, customer_id: int, channel: str,
    campaign_id: Optional[int] = None,
) -> ContactDecision:
    """May we contact this customer on this channel, right now?

    Counts contacts across ALL campaigns — that is the whole point. Every gate
    returns a specific reason code so the Decision Trace can say which limit
    bound, rather than a generic refusal.
    """
    # --- consent, re-checked NOW -------------------------------------------
    consent = (await db.execute(
        text("""SELECT granted, max_contacts_per_week
                  FROM flywheel_customer_consents
                 WHERE tenant_id = :t AND customer_id = :c AND channel = :ch"""),
        {"t": tenant_id, "c": customer_id, "ch": channel},
    )).fetchone()
    if consent is not None and not consent[0]:
        return ContactDecision(False, "NO_CONSENT",
                               f"Customer has not consented to {channel}")

    status = (await db.execute(
        text("SELECT status FROM flywheel_customers WHERE id = :c AND tenant_id = :t"),
        {"c": customer_id, "t": tenant_id},
    )).scalar()
    if status == "opted_out":
        return ContactDecision(False, "NO_CONSENT", "Customer has opted out entirely")

    policy = await _policy(db, tenant_id, channel)

    # The customer's OWN declared limit wins when it is tighter than the
    # tenant policy — a preference is a floor on our behaviour, not a hint.
    customer_weekly = int(consent[1]) if consent and consent[1] is not None else None
    weekly_cap = min(policy["week"], customer_weekly) if customer_weekly is not None \
        else policy["week"]

    # --- counts, ACROSS ALL CAMPAIGNS --------------------------------------
    counts = (await db.execute(
        text("""SELECT
                  COUNT(*) FILTER (WHERE contacted_at >= now() - INTERVAL '1 day'),
                  COUNT(*) FILTER (WHERE contacted_at >= now() - INTERVAL '7 days'
                                     AND channel = :ch),
                  COUNT(*) FILTER (WHERE contacted_at >= now() - INTERVAL '7 days')
                  FROM flywheel_contact_log
                 WHERE tenant_id = :t AND customer_id = :c"""),
        {"t": tenant_id, "c": customer_id, "ch": channel},
    )).fetchone()
    today_count, channel_week, all_week = (int(counts[0]), int(counts[1]), int(counts[2]))
    observed = {"today": today_count, "this_channel_7d": channel_week,
                "all_channels_7d": all_week,
                "cap_day": policy["day"], "cap_week": weekly_cap}

    if today_count >= policy["day"]:
        return ContactDecision(False, "CONTACT_CAP_REACHED",
                               f"Daily cap of {policy['day']} already reached "
                               f"across all campaigns", observed)

    if channel_week >= weekly_cap:
        return ContactDecision(False, "CONTACT_CAP_REACHED",
                               f"Weekly {channel} cap of {weekly_cap} already "
                               f"reached across all campaigns", observed)

    # --- the all-channel ceiling — the gap v1 had no concept of -------------
    all_channel_policy = await _policy(db, tenant_id, None)
    if all_week >= all_channel_policy["week"]:
        return ContactDecision(
            False, "GLOBAL_CONTACT_CAP_REACHED",
            f"Customer has had {all_week} contacts across all channels this "
            f"week against a ceiling of {all_channel_policy['week']}", observed)

    # --- ignore cooldown ---------------------------------------------------
    # Someone who ignored the last N offers is signalling fatigue. Continuing to
    # send is how a channel gets burned and consent gets revoked.
    recent = (await db.execute(
        text("""SELECT event_type FROM flywheel_customer_events
                 WHERE tenant_id = :t AND customer_id = :c
                   AND event_type IN ('offer_ignored', 'offer_redeemed')
                 ORDER BY occurred_at DESC
                 LIMIT :n"""),
        {"t": tenant_id, "c": customer_id, "n": policy["ignores"]},
    )).fetchall()
    if len(recent) >= policy["ignores"] and all(r[0] == "offer_ignored" for r in recent):
        last_contact = (await db.execute(
            text("""SELECT EXTRACT(DAY FROM (now() - MAX(contacted_at)))
                      FROM flywheel_contact_log
                     WHERE tenant_id = :t AND customer_id = :c"""),
            {"t": tenant_id, "c": customer_id},
        )).scalar()
        if last_contact is not None and int(last_contact) < policy["cooldown_days"]:
            return ContactDecision(
                False, "IGNORE_COOLDOWN",
                f"Ignored the last {policy['ignores']} offers; in a "
                f"{policy['cooldown_days']}-day cooldown "
                f"({int(last_contact)} days elapsed)", observed)

    return ContactDecision(True, "", "Within all contact limits", observed)


async def resolve_campaign_conflict(
    db: AsyncSession, *, tenant_id: int, customer_id: int,
    candidate_campaign_ids: List[int],
) -> Dict[str, Any]:
    """Pick exactly ONE campaign when a customer qualifies for several.

    Deterministic and total: priority ascending, then higher recent EIV, then
    lower campaign id. The final tiebreak on id matters — without it the winner
    could depend on row order, and the same customer could flip between
    campaigns on successive evaluations.

    An EXCLUSIVE campaign wins outright over any non-exclusive one, because
    that is what exclusivity means; two exclusive campaigns fall back to the
    normal ordering.
    """
    if not candidate_campaign_ids:
        return {"winner": None, "suppressed": []}
    if len(candidate_campaign_ids) == 1:
        return {"winner": candidate_campaign_ids[0], "suppressed": []}

    rows = (await db.execute(
        text("""SELECT c.id, c.priority, c.is_exclusive, c.name,
                       COALESCE((SELECT AVG(d.eiv_aed) FROM flywheel_decisions d
                                  WHERE d.campaign_id = c.id
                                    AND d.action_type <> 'NO_ACTION'), 0) AS avg_eiv
                  FROM flywheel_campaigns c
                 WHERE c.tenant_id = :t AND c.id = ANY(:ids) AND c.status = 'ACTIVE'"""),
        {"t": tenant_id, "ids": candidate_campaign_ids},
    )).fetchall()
    if not rows:
        return {"winner": None, "suppressed": []}

    candidates = [{"id": int(r[0]), "priority": int(r[1]), "exclusive": bool(r[2]),
                   "name": r[3], "avg_eiv": Decimal(str(r[4] or 0))} for r in rows]

    ordered = sorted(
        candidates,
        key=lambda c: (not c["exclusive"], c["priority"], -c["avg_eiv"], c["id"]),
    )
    winner, losers = ordered[0], ordered[1:]

    for loser in losers:
        reason = ("CAMPAIGN_EXCLUSIVITY" if winner["exclusive"]
                  else "LOWER_PRIORITY" if loser["priority"] > winner["priority"]
                  else "LOWER_EXPECTED_VALUE")
        await db.execute(
            text("""INSERT INTO flywheel_offer_suppressions
                       (tenant_id, customer_id, suppressed_campaign_id,
                        winning_campaign_id, reason_code, detail)
                    VALUES (:t, :c, :sup, :win, :rc, :detail)"""),
            {"t": tenant_id, "c": customer_id, "sup": loser["id"],
             "win": winner["id"], "rc": reason,
             "detail": f"'{loser['name']}' (priority {loser['priority']}, "
                       f"avg EIV {loser['avg_eiv']}) lost to '{winner['name']}' "
                       f"(priority {winner['priority']}, avg EIV {winner['avg_eiv']})"},
        )

    return {
        "winner": winner["id"], "winner_name": winner["name"],
        "suppressed": [{"campaign_id": l["id"], "name": l["name"]} for l in losers],
        "rule": "exclusive first, then lowest priority, then highest average EIV, "
                "then lowest id",
    }


async def record_contact(
    db: AsyncSession, *, tenant_id: int, customer_id: int, channel: str,
    campaign_id: Optional[int] = None,
) -> None:
    """Log a contact. Must be called in the same transaction as issuing the
    offer, or the cap can be bypassed by a crash between the two."""
    await db.execute(
        text("""INSERT INTO flywheel_contact_log
                   (tenant_id, customer_id, campaign_id, channel)
                VALUES (:t, :c, :camp, :ch)"""),
        {"t": tenant_id, "c": customer_id, "camp": campaign_id, "ch": channel},
    )


async def contact_status(
    db: AsyncSession, *, tenant_id: int, customer_id: int
) -> Dict[str, Any]:
    """Full contact picture for the Customer View — per channel and overall."""
    rows = (await db.execute(
        text("""SELECT channel,
                       COUNT(*) FILTER (WHERE contacted_at >= now() - INTERVAL '7 days'),
                       COUNT(*) FILTER (WHERE contacted_at >= now() - INTERVAL '1 day'),
                       MAX(contacted_at)
                  FROM flywheel_contact_log
                 WHERE tenant_id = :t AND customer_id = :c
                 GROUP BY channel"""),
        {"t": tenant_id, "c": customer_id},
    )).fetchall()
    total_week = (await db.execute(
        text("""SELECT COUNT(*) FROM flywheel_contact_log
                 WHERE tenant_id = :t AND customer_id = :c
                   AND contacted_at >= now() - INTERVAL '7 days'"""),
        {"t": tenant_id, "c": customer_id},
    )).scalar() or 0
    ceiling = await _policy(db, tenant_id, None)
    return {
        "by_channel": [{"channel": r[0], "last_7_days": int(r[1]),
                        "today": int(r[2]),
                        "last_contact": r[3].isoformat() if r[3] else None}
                       for r in rows],
        "all_channels_7d": int(total_week),
        "all_channels_ceiling": ceiling["week"],
        "headroom": max(0, ceiling["week"] - int(total_week)),
    }


async def overview(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """Everything the Contact Governance surface needs, in one call.

    WHY THIS EXISTS. All four gates above, the policy table and the suppression
    ledger have been enforced since migration 076 and have never been visible in
    the product. A marketer could not see the caps they were subject to, could
    not see who was suppressed, and could not see how often the system declined
    to send. Enforcement they cannot inspect is enforcement they will not trust,
    and the first thing an operator does with a system they do not trust is
    route around it.

    THE SUPPRESSED COUNT IS A FEATURE. It is the system declining to
    over-contact people, which is the whole purpose of the module. Rendered as
    a failure metric it would train operators to raise the caps until it went
    away, so it is labelled here rather than left for the UI to interpret.
    """
    policies = (await db.execute(
        text("""SELECT channel, max_contacts_per_week, max_contacts_per_day,
                       cooldown_days_after_ignores, ignores_before_cooldown,
                       is_active
                  FROM flywheel_contact_policy
                 WHERE tenant_id = :t
                 ORDER BY channel"""),
        {"t": tenant_id},
    )).fetchall()

    # Contact volume by channel over the trailing week.
    volume = (await db.execute(
        text("""SELECT channel,
                       COUNT(*) FILTER (WHERE contacted_at >= now() - interval '1 day'),
                       COUNT(*) FILTER (WHERE contacted_at >= now() - interval '7 days'),
                       COUNT(DISTINCT customer_id)
                         FILTER (WHERE contacted_at >= now() - interval '7 days')
                  FROM flywheel_contact_log
                 WHERE tenant_id = :t
                 GROUP BY channel
                 ORDER BY channel"""),
        {"t": tenant_id},
    )).fetchall()
    volume_by_channel = {
        r[0]: {"last_24h": int(r[1]), "last_7d": int(r[2]),
               "distinct_customers_7d": int(r[3])}
        for r in volume
    }

    # FATIGUE. Customers nearest their weekly ceiling — the people most at risk
    # of being over-contacted, which is what an operator actually wants to see.
    fatigue = (await db.execute(
        text("""SELECT customer_id, COUNT(*) AS contacts,
                       MAX(contacted_at) AS last_contact
                  FROM flywheel_contact_log
                 WHERE tenant_id = :t
                   AND contacted_at >= now() - interval '7 days'
                 GROUP BY customer_id
                 HAVING COUNT(*) >= 2
                 ORDER BY COUNT(*) DESC, MAX(contacted_at) DESC
                 LIMIT 50"""),
        {"t": tenant_id},
    )).fetchall()

    suppressions = (await db.execute(
        text("""SELECT reason_code, COUNT(*)
                  FROM flywheel_offer_suppressions
                 WHERE tenant_id = :t
                   AND created_at >= now() - interval '30 days'
                 GROUP BY reason_code
                 ORDER BY COUNT(*) DESC"""),
        {"t": tenant_id},
    )).fetchall()

    recent_suppressions = (await db.execute(
        text("""SELECT s.customer_id, s.suppressed_campaign_id, s.winning_campaign_id,
                       s.reason_code, s.detail, s.created_at,
                       sc.name, wc.name
                  FROM flywheel_offer_suppressions s
                  LEFT JOIN flywheel_campaigns sc ON sc.id = s.suppressed_campaign_id
                  LEFT JOIN flywheel_campaigns wc ON wc.id = s.winning_campaign_id
                 WHERE s.tenant_id = :t
                 ORDER BY s.created_at DESC
                 LIMIT 25"""),
        {"t": tenant_id},
    )).fetchall()

    total_suppressed = sum(int(r[1]) for r in suppressions)

    return {
        "policies": [{
            "channel": r[0], "max_per_week": int(r[1]), "max_per_day": int(r[2]),
            "cooldown_days_after_ignores": int(r[3]),
            "ignores_before_cooldown": int(r[4]), "is_active": bool(r[5]),
            "volume": volume_by_channel.get(r[0], {"last_24h": 0, "last_7d": 0,
                                                   "distinct_customers_7d": 0}),
        } for r in policies],
        "fatigue": [{
            "customer_id": int(r[0]), "contacts_7d": int(r[1]),
            "last_contact": r[2].isoformat() if r[2] else None,
        } for r in fatigue],
        "suppressions_by_reason": {r[0]: int(r[1]) for r in suppressions},
        "suppressed_30d": total_suppressed,
        "recent_suppressions": [{
            "customer_id": int(r[0]),
            "suppressed_campaign_id": int(r[1]) if r[1] is not None else None,
            "winning_campaign_id": int(r[2]) if r[2] is not None else None,
            "reason_code": r[3], "detail": r[4],
            "created_at": r[5].isoformat() if r[5] else None,
            "suppressed_campaign_name": r[6], "winning_campaign_name": r[7],
        } for r in recent_suppressions],
        "interpretation": (
            f"{total_suppressed} contacts were withheld in the last 30 days by "
            f"policy. That is the system working: each one is a message a "
            f"customer did not receive because they had already heard enough. "
            f"A rising number is not a fault to be tuned away."
        ),
    }
