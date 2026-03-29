"""Audit trail router — blueprint §10 compliance backbone."""
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db.database import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


class OverrideBody(BaseModel):
    override_reason: str
    overridden_by: str


@router.get("/")
async def list_audit(
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    final_status: Optional[str] = Query(None),
    db: asyncpg.Connection = Depends(get_db),
):
    if final_status:
        rows = await db.fetch("""
            SELECT * FROM audit_trail WHERE final_status=$1
            ORDER BY timestamp DESC LIMIT $2 OFFSET $3
        """, final_status, limit, offset)
    else:
        rows = await db.fetch("""
            SELECT * FROM audit_trail
            ORDER BY timestamp DESC LIMIT $1 OFFSET $2
        """, limit, offset)
    return [dict(r) for r in rows]


@router.get("/summary")
async def audit_summary(
    period: str = Query("month", regex="^(month|week)$"),
    db: asyncpg.Connection = Depends(get_db),
):
    from agents.audit_agent import AuditAgent
    agent = AuditAgent(db)
    return await agent.get_summary(db, period)


@router.get("/{audit_id}")
async def get_audit_record(audit_id: str, db: asyncpg.Connection = Depends(get_db)):
    row = await db.fetchrow("SELECT * FROM audit_trail WHERE audit_id=$1", audit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Audit record not found")
    return dict(row)


@router.post("/{audit_id}/override")
async def override_audit(
    audit_id: str,
    body: OverrideBody,
    db: asyncpg.Connection = Depends(get_db),
):
    """
    Override an audit trail decision and release related payment holds.
    Blueprint §10 - Human override capability.
    """
    # Update audit record status
    row = await db.fetchrow("""
        UPDATE audit_trail
        SET final_status = 'overridden',
            override_reason = $2,
            overridden_at = NOW(),
            overridden_by = $3
        WHERE audit_id = $1
        RETURNING audit_id, final_status
    """, audit_id, body.override_reason, body.overridden_by)
    
    if not row:
        raise HTTPException(status_code=404, detail="Audit record not found")
    
    # Release related payment holds if applicable
    await db.execute("""
        UPDATE actions_taken 
        SET status = 'rolled_back',
            rolled_back_at = NOW()
        WHERE anomaly_id IN (
            SELECT input_data->>'anomaly_id' 
            FROM audit_trail 
            WHERE audit_id = $1
        )
        AND action_type = 'payment_hold'
        AND status = 'success'
    """, audit_id)
    
    return {"status": "ok", "message": "Audit decision overridden"}