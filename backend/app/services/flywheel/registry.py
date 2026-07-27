"""Model registry — bind a model to the exact data it was trained on.

WHY A HASH OF THE DATA. Ruling #1 (20 Jul 2026) promotes a model only when a
pre-registered holdout shows it beating rules. That criterion is unenforceable
unless you can prove WHICH DATA a model saw: a model trained on last month's
customers cannot be judged against this month's holdout, and "our model scored
0.92" is meaningless without "…on this snapshot of 300 customers as of this
date". So every registered model carries a DATA_SNAPSHOT_HASH — a deterministic
fingerprint of its training rows. Two models with the same hash are comparable;
two with different hashes are not, and the registry says so out loud rather than
letting them be compared silently.

WHY ROLLBACK IS FIRST-CLASS. A promoted model that misbehaves in production must
be revertible in one call, to a KNOWN-GOOD prior version, with the reversal
recorded. "We turned the model off" is not a rollback; "we restored version 7,
which was live before version 9 was promoted on the 14th, because 9's
disagreement rate spiked" is. The lifecycle columns (migration 078) make that
sentence answerable from the data.

WHAT THIS IS NOT. It is not a model server and not an artifact store — artifacts
live at artifact_path on disk/S3 as before. This is the LEDGER of which model is
live, what it was trained on, and how it got there. The governing rule holds: a
model in this registry proposes; it never disposes. Promotion here only changes
which scores the rule tier reads, never whether a model can move money.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date
from typing import Any, Dict, List, Optional


def _as_date(value: Any) -> Optional[date]:
    """asyncpg binds a DATE column strictly — it wants a date object, not an ISO
    string, and rejects the string even through a CAST. compute_snapshot returns
    ISO strings for its API callers, so parse them back before the DB write."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def compute_snapshot(
    db: AsyncSession, *, tenant_id: int, as_of: Optional[date] = None
) -> Dict[str, Any]:
    """Fingerprint the training data at `as_of`.

    The hash is over the SORTED (customer_id, as_of_date, feature-digest) of every
    feature snapshot the model would train on. Sorting makes it order-independent;
    including the feature values (not just ids) means a correction to a customer's
    history changes the hash, because it genuinely changed what the model saw.

    Computed in the database with md5() over a deterministic string_agg, so it is
    cheap and does not stream every row into Python.
    """
    as_of = as_of or (await db.execute(
        text("""SELECT MAX(as_of_date) FROM flywheel_feature_snapshots
                 WHERE tenant_id = :t"""),
        {"t": tenant_id},
    )).scalar()

    if as_of is None:
        return {"hash": None, "rows": 0, "from": None, "to": None,
                "note": "no feature snapshots to fingerprint"}

    row = (await db.execute(
        text("""SELECT
                    md5(string_agg(
                        customer_id::text || ':' || as_of_date::text || ':' ||
                        md5(row_to_json(fs)::text),
                        '|' ORDER BY customer_id)) AS snap_hash,
                    COUNT(*) AS rows,
                    MIN(as_of_date) AS from_d,
                    MAX(as_of_date) AS to_d
                  FROM flywheel_feature_snapshots fs
                 WHERE tenant_id = :t AND as_of_date = :d"""),
        {"t": tenant_id, "d": as_of},
    )).fetchone()

    return {
        "hash": row[0], "rows": int(row[1] or 0),
        "from": str(row[2]) if row[2] else None,
        "to": str(row[3]) if row[3] else None,
    }


async def register_snapshot(
    db: AsyncSession, *, tenant_id: int, model_version_id: int,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Attach a data-snapshot fingerprint to an existing model version.

    Called after training. Idempotent: re-registering the same version with the
    same data writes the same hash. If the version already has a DIFFERENT hash,
    that is refused — a model version is meant to be immutable evidence of one
    training run, and silently overwriting its provenance would defeat the point.
    """
    snap = await compute_snapshot(db, tenant_id=tenant_id, as_of=as_of)
    if snap["hash"] is None:
        raise ValueError("no training data to fingerprint")

    existing = (await db.execute(
        text("""SELECT data_snapshot_hash FROM flywheel_model_versions
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": model_version_id},
    )).fetchone()
    if existing is None:
        raise ValueError(f"model version {model_version_id} not found")
    if existing[0] and existing[0] != snap["hash"]:
        raise ValueError(
            f"model version {model_version_id} is already bound to a different "
            f"data snapshot ({existing[0][:12]}…). A version's provenance is "
            f"immutable — register a NEW version for new data.")

    await db.execute(
        text("""UPDATE flywheel_model_versions
                   SET data_snapshot_hash = :h, data_snapshot_rows = :r,
                       data_snapshot_from = :f, data_snapshot_to = :to_d
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": model_version_id, "h": snap["hash"],
         "r": snap["rows"], "f": _as_date(snap["from"]), "to_d": _as_date(snap["to"])},
    )
    logger.info("flywheel.registry bound version=%s snapshot=%s rows=%s",
                model_version_id, snap["hash"][:12], snap["rows"])
    return {"model_version_id": model_version_id, **snap}


async def promote(
    db: AsyncSession, *, tenant_id: int, model_version_id: int,
    promoted_by: Optional[int] = None, note: Optional[str] = None,
) -> Dict[str, Any]:
    """Make a version the live one, recording what it replaced.

    Sets the new version promoted + is_active, points the previously-active
    version's superseded_by at it, and stamps who/when/why. The whole thing is one
    transaction (the caller's), so there is never a window with two active models
    or none.

    REFUSES to promote a version with no data snapshot: a model whose training
    data cannot be identified cannot satisfy the promotion criterion, so it is not
    eligible to be live. This is the guardrail that keeps ruling #1 honest.
    """
    version = (await db.execute(
        text("""SELECT model_kind, data_snapshot_hash, lifecycle_status
                  FROM flywheel_model_versions
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": model_version_id},
    )).fetchone()
    if version is None:
        raise ValueError(f"model version {model_version_id} not found")
    model_kind, snapshot_hash, status = version
    if not snapshot_hash:
        raise ValueError(
            f"version {model_version_id} has no data-snapshot fingerprint — bind "
            f"one with register_snapshot before it can be promoted. A model whose "
            f"training data cannot be identified is not eligible to go live.")

    # Demote whatever is currently active for this model kind, and record that
    # this version superseded it.
    previous = (await db.execute(
        text("""SELECT id FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = :k AND is_active = TRUE
                   AND id <> :v"""),
        {"t": tenant_id, "k": model_kind, "v": model_version_id},
    )).fetchall()
    for (prev_id,) in previous:
        await db.execute(
            text("""UPDATE flywheel_model_versions
                       SET is_active = FALSE, superseded_by = :new,
                           lifecycle_status = CASE
                               WHEN lifecycle_status = 'promoted' THEN 'retired'
                               ELSE lifecycle_status END
                     WHERE tenant_id = :t AND id = :prev"""),
            {"t": tenant_id, "new": model_version_id, "prev": int(prev_id)},
        )

    await db.execute(
        text("""UPDATE flywheel_model_versions
                   SET is_active = TRUE, lifecycle_status = 'promoted',
                       promoted_at = now(), promoted_by = :by, promotion_note = :note
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": model_version_id, "by": promoted_by, "note": note},
    )
    logger.info("flywheel.registry promoted version=%s kind=%s (was %s)",
                model_version_id, model_kind, [int(p[0]) for p in previous])
    return {"promoted": model_version_id, "model_kind": model_kind,
            "superseded": [int(p[0]) for p in previous]}


async def rollback(
    db: AsyncSession, *, tenant_id: int, to_version_id: int,
    actor_id: Optional[int] = None, reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Revert to a known-good prior version, recording the reversal.

    Marks the currently-active version rolled_back (pointing at the version being
    restored) and re-activates the target. Unlike promote, rollback does NOT
    require the target to re-pass the promotion bar — it was live before, so it is
    known-good, and speed matters when a live model is misbehaving.
    """
    target = (await db.execute(
        text("""SELECT model_kind, data_snapshot_hash FROM flywheel_model_versions
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": to_version_id},
    )).fetchone()
    if target is None:
        raise ValueError(f"rollback target version {to_version_id} not found")
    model_kind = target[0]

    current = (await db.execute(
        text("""SELECT id FROM flywheel_model_versions
                 WHERE tenant_id = :t AND model_kind = :k AND is_active = TRUE"""),
        {"t": tenant_id, "k": model_kind},
    )).fetchall()
    for (cur_id,) in current:
        if int(cur_id) == to_version_id:
            continue
        await db.execute(
            text("""UPDATE flywheel_model_versions
                       SET is_active = FALSE, lifecycle_status = 'rolled_back',
                           rolled_back_to = :target,
                           promotion_note = COALESCE(promotion_note, '') ||
                               ' [rolled back: ' || COALESCE(:reason, 'no reason given') || ']'
                     WHERE tenant_id = :t AND id = :cur"""),
            {"t": tenant_id, "target": to_version_id, "cur": int(cur_id),
             "reason": reason},
        )

    await db.execute(
        text("""UPDATE flywheel_model_versions
                   SET is_active = TRUE, lifecycle_status = 'promoted',
                       promoted_at = now(), promoted_by = :by
                 WHERE tenant_id = :t AND id = :v"""),
        {"t": tenant_id, "v": to_version_id, "by": actor_id},
    )
    logger.warning("flywheel.registry ROLLBACK kind=%s to version=%s (reason=%s)",
                   model_kind, to_version_id, reason)
    return {"rolled_back_to": to_version_id, "model_kind": model_kind,
            "deactivated": [int(c[0]) for c in current if int(c[0]) != to_version_id]}


async def list_versions(db: AsyncSession, *, tenant_id: int) -> Dict[str, Any]:
    """Every model version with its provenance and lineage — the registry view."""
    rows = (await db.execute(
        text("""SELECT id, model_kind, algorithm, version_label, is_active,
                       lifecycle_status, data_snapshot_hash, data_snapshot_rows,
                       data_snapshot_from, data_snapshot_to, superseded_by,
                       rolled_back_to, promoted_at, metrics, trained_at
                  FROM flywheel_model_versions
                 WHERE tenant_id = :t
                 ORDER BY model_kind, id DESC"""),
        {"t": tenant_id},
    )).fetchall()

    versions = [{
        "id": int(r[0]), "model_kind": r[1], "algorithm": r[2],
        "version_label": r[3], "is_active": bool(r[4]),
        "lifecycle_status": r[5] or "shadow",
        "data_snapshot_hash": r[6],
        "data_snapshot_short": (r[6][:12] + "…") if r[6] else None,
        "reproducible": r[6] is not None,
        "data_snapshot_rows": int(r[7]) if r[7] is not None else None,
        "data_snapshot_from": str(r[8]) if r[8] else None,
        "data_snapshot_to": str(r[9]) if r[9] else None,
        "superseded_by": int(r[10]) if r[10] is not None else None,
        "rolled_back_to": int(r[11]) if r[11] is not None else None,
        "promoted_at": r[12].isoformat() if r[12] else None,
        "metrics": r[13],
        "trained_at": r[14].isoformat() if r[14] else None,
    } for r in rows]

    unbound = [v["id"] for v in versions if not v["reproducible"]]
    return {
        "versions": versions,
        "count": len(versions),
        "unreproducible": unbound,
        "note": (
            "A version without a data-snapshot fingerprint (reproducible=false) "
            "cannot be promoted — its training data cannot be identified, so it "
            "cannot be judged against a holdout. These are legacy or in-progress "
            "versions." if unbound else
            "Every version is bound to a data snapshot and can be reproduced and "
            "judged."),
    }
