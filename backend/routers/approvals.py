"""
Approvals router — human-in-the-loop governance endpoints.

Endpoints:
  GET  /api/approvals/          — fetch all pending approvals
  GET  /api/approvals/stats     — counts by state for dashboard badge
  POST /api/approvals/{id}/approve  — approve and trigger execution
  POST /api/approvals/{id}/reject   — reject without executing
  POST /api/approvals/{id}/override — reverse an already-executed action

Blueprint §8A + §11A.
"""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.database import get_db
from services.approval_service import (
    get_pending_approvals,
    approve_action,
    reject_action,
    override_action,
)
from core.constants import ActionState

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


# ─── Request bodies ────────────────────────────────────────────────────────
class ApproveRequest(BaseModel):
    approved_by: str


class RejectRequest(BaseModel):
    rejected_by: str
    reason: str


class OverrideRequest(BaseModel):
    overridden_by: str
    reason: str


# ─── Endpoints ────────────────────────────────────────────────────────────
@router.get("/")
async def list_pending_approvals(db: asyncpg.Connection = Depends(get_db)):
    """
    Returns all actions in PENDING_APPROVAL state.
    Drives the Approval Queue component in the dashboard.
    """
    return await get_pending_approvals(db)


@router.get("/stats")
async def approval_stats(db: asyncpg.Connection = Depends(get_db)):
    """Counts by action state — used by dashboard badges."""
    rows = await db.fetch("""
        SELECT status, COUNT(*) AS count
        FROM actions_taken
        GROUP BY status
        ORDER BY status
    """)
    stats = {r["status"]: r["count"] for r in rows}
    return {
        "pending_approval": stats.get(ActionState.PENDING_APPROVAL.value, 0),
        "approved": stats.get(ActionState.APPROVED.value, 0),
        "rejected": stats.get(ActionState.REJECTED.value, 0),
        "success": stats.get(ActionState.SUCCESS.value, 0),
        "overridden": stats.get(ActionState.OVERRIDDEN.value, 0),
        "rolled_back": stats.get(ActionState.ROLLED_BACK.value, 0),
        "total": sum(stats.values()),
    }


@router.post("/{action_id}/approve")
async def approve(
    action_id: UUID,
    body: ApproveRequest,
    db: asyncpg.Connection = Depends(get_db),
):
    """
    Approve a pending action and trigger its execution.
    Blueprint §8A: on approval → Action Execution Agent triggers action.
    """
    try:
        action = await approve_action(db, action_id, body.approved_by)
        return {
            "message": f"Action approved and executed by {body.approved_by}",
            "action": action,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval failed: {e}")


@router.post("/{action_id}/reject")
async def reject(
    action_id: UUID,
    body: RejectRequest,
    db: asyncpg.Connection = Depends(get_db),
):
    """Reject a pending action — it will not be executed."""
    try:
        action = await reject_action(db, action_id, body.rejected_by, body.reason)
        return {
            "message": f"Action rejected by {body.rejected_by}",
            "action": action,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{action_id}/override")
async def override(
    action_id: UUID,
    body: OverrideRequest,
    db: asyncpg.Connection = Depends(get_db),
):
    """
    Override and reverse an already-executed action (false positive recovery).
    Blueprint §11A: Finance user identifies false positive → system reverses action.
    """
    try:
        action = await override_action(db, action_id, body.overridden_by, body.reason)
        return {
            "message": f"Action reversed by {body.overridden_by}",
            "audit_note": "Override recorded in audit trail. Payment/license status restored.",
            "action": action,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Override failed: {e}")


@router.get("/{action_id}")
async def get_action_detail(
    action_id: UUID,
    db: asyncpg.Connection = Depends(get_db),
):
    """Full detail for a single action including anomaly context."""
    row = await db.fetchrow("""
        SELECT
            a.*,
            al.anomaly_type,
            al.severity,
            al.confidence,
            al.reasoning,
            al.root_cause,
            al.cost_impact_inr AS anomaly_cost_impact
        FROM actions_taken a
        LEFT JOIN anomaly_logs al ON a.anomaly_id = al.id
        WHERE a.id = $1
    """, action_id)

    if not row:
        raise HTTPException(status_code=404, detail="Action not found")
    return dict(row)