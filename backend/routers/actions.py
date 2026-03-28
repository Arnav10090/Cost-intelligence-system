"""Actions router — execution history and manual rollback."""
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from db.database import get_db

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("/")
async def list_actions(
    status: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    db: asyncpg.Connection = Depends(get_db),
):
    conditions, params = ["1=1"], []
    if status:
        params.append(status)
        conditions.append(f"a.status = ${len(params)}")
    if action_type:
        params.append(action_type)
        conditions.append(f"a.action_type = ${len(params)}")
    params.append(limit)
    rows = await db.fetch(f"""
        SELECT a.*, al.anomaly_type, al.severity, al.confidence
        FROM actions_taken a
        LEFT JOIN anomaly_logs al ON a.anomaly_id = al.id
        WHERE {' AND '.join(conditions)}
        ORDER BY a.executed_at DESC LIMIT ${len(params)}
    """, *params)
    return [dict(r) for r in rows]


@router.get("/{action_id}")
async def get_action(action_id: UUID, db: asyncpg.Connection = Depends(get_db)):
    row = await db.fetchrow("""
        SELECT a.*, al.anomaly_type, al.severity, al.reasoning, al.root_cause
        FROM actions_taken a
        LEFT JOIN anomaly_logs al ON a.anomaly_id = al.id
        WHERE a.id = $1
    """, action_id)
    if not row:
        raise HTTPException(status_code=404, detail="Action not found")
    return dict(row)


@router.post("/{action_id}/rollback")
async def rollback_action(
    action_id: UUID,
    reason: str = Query(...),
    rolled_back_by: str = Query(...),
    db: asyncpg.Connection = Depends(get_db),
):
    from services.approval_service import override_action
    try:
        result = await override_action(db, action_id, rolled_back_by, reason)
        return {"message": "Action rolled back", "action": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))