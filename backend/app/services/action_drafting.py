"""
Action drafting — autonomy level 1 (human-approved, never auto-executed).

Maps a finding's coarse `action_type` to a concrete, human-approvable DRAFT artifact
using deterministic templates (NO LLM — every word is derivable and safe). The
system drafts; a human approves; a human executes. Approval records a decision and
NEVER sends an email, places an order, or changes prices on its own.

The mapper (`build_draft`) is pure and unit-tested. The async helpers persist drafts
and record human review. PO replenishment drafting lives in procurement_service
(approval_rules); this covers the communication/decision actions findings produce.
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# action_type (from the worker rules) -> draft_type.
ACTION_TO_DRAFT = {
    "review_supplier": "supplier_email",
    "review_pricing":  "markdown_proposal",
    "promote":         "promotion_proposal",
    "investigate":     "review_task",
}
_DEFAULT_DRAFT = "review_task"

DRAFT_TYPES = {"supplier_email", "markdown_proposal", "promotion_proposal",
               "review_task", "purchase_order"}


def _entity_label(finding: Dict) -> str:
    name = finding.get("entity_name") or finding.get("entity_id") or "the affected entity"
    etype = finding.get("entity_type") or "entity"
    return f"{etype} {name}" if finding.get("entity_name") else str(name)


def build_draft(finding: Dict) -> Dict:
    """Build a deterministic draft artifact from a finding. Returns
    {draft_type, title, summary, payload, source_action_type}. Pure — no I/O."""
    action_type = (finding.get("action_type") or "investigate").lower()
    draft_type = ACTION_TO_DRAFT.get(action_type, _DEFAULT_DRAFT)
    entity = _entity_label(finding)
    title_text = finding.get("title") or "Operational finding"
    detail = finding.get("detail") or ""
    rec = finding.get("recommended_action") or "Review and decide on a corrective action."

    if draft_type == "supplier_email":
        payload = {
            "to": "<supplier contact — fill in>",
            "subject": f"Supply review: {title_text}",
            "body": (
                f"Hello,\n\n"
                f"Our operations review flagged an issue relating to {entity}.\n"
                f"{detail}\n\n"
                f"Could you confirm current lead times, availability and pricing so we "
                f"can avoid disruption? Suggested next step on our side: {rec}\n\n"
                f"Thank you,\nProcurement team"
            ),
        }
        summary = f"Draft email to the supplier behind {entity}."
    elif draft_type == "markdown_proposal":
        payload = {
            "entity": entity,
            "rationale": detail or title_text,
            "proposed_steps": [
                f"Review current margin and price position for {entity}.",
                "Model a markdown scenario and its effect on sell-through.",
                "If approved, schedule the markdown and tag it for outcome tracking.",
            ],
        }
        summary = f"Draft markdown/price review for {entity}."
    elif draft_type == "promotion_proposal":
        payload = {
            "entity": entity,
            "rationale": detail or title_text,
            "proposed_promo": f"Targeted promotion on {entity} to lift demand.",
            "next_steps": ["Confirm budget and period", "Define mechanic", "Track lift vs baseline"],
        }
        summary = f"Draft promotion proposal for {entity}."
    else:  # review_task
        payload = {
            "task": f"Investigate: {title_text}",
            "context": detail,
            "recommended_action": rec,
            "entity": entity,
        }
        summary = f"Draft review task for {entity}."

    return {
        "draft_type": draft_type,
        "title": f"Draft: {title_text}",
        "summary": summary,
        "payload": payload,
        "source_action_type": action_type,
    }


async def create_draft_from_finding(db: AsyncSession, tenant_id: int, finding_id: int,
                                    created_by: str) -> Optional[Dict]:
    """Build + persist a draft from a tenant's finding. Returns the draft row, or
    None if the finding doesn't exist for this tenant."""
    import json
    f = (await db.execute(text("""
        SELECT id, title, detail, entity_type, entity_id, entity_name,
               recommended_action, action_type
        FROM findings WHERE id = :fid AND tenant_id = :tid
    """), {"fid": finding_id, "tid": tenant_id})).mappings().fetchone()
    if not f:
        return None
    d = build_draft(dict(f))
    row = (await db.execute(text("""
        INSERT INTO action_drafts (tenant_id, finding_id, draft_type, status, title,
            summary, payload, source_action_type, created_by)
        VALUES (:tid, :fid, :dtype, 'draft', :title, :summary, CAST(:payload AS JSONB),
                :sat, :by)
        RETURNING id, draft_type, status, title, summary, created_at
    """), {"tid": tenant_id, "fid": finding_id, "dtype": d["draft_type"],
           "title": d["title"], "summary": d["summary"],
           "payload": json.dumps(d["payload"]), "sat": d["source_action_type"],
           "by": created_by})).mappings().fetchone()
    return {**dict(row), "created_at": row["created_at"].isoformat() if row["created_at"] else None}


async def review_draft(db: AsyncSession, tenant_id: int, draft_id: int, *,
                       decision: str, reviewer: str, note: Optional[str]) -> Optional[Dict]:
    """Approve or reject a draft (human decision). Approval does NOT execute the
    action — it records that a human signed off; execution stays manual. Returns the
    updated row, or None if not found / not in 'draft'."""
    if decision not in ("approved", "rejected"):
        return None
    row = (await db.execute(text("""
        UPDATE action_drafts
           SET status = :st, reviewed_by = :by, review_note = :note,
               reviewed_at = now(), updated_at = now()
         WHERE id = :id AND tenant_id = :tid AND status = 'draft'
         RETURNING id, draft_type, status, title, reviewed_by, finding_id
    """), {"st": decision, "by": reviewer, "note": note,
           "id": draft_id, "tid": tenant_id})).mappings().fetchone()
    return dict(row) if row else None
