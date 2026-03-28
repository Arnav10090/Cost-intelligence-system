"""Anomalies router — detection feed for the dashboard."""
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from db.database import get_db

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("/")
async def list_anomalies(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    anomaly_type: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    db: asyncpg.Connection = Depends(get_db),
):
    conditions = ["1=1"]
    params: list = []

    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")
    if severity:
        params.append(severity)
        conditions.append(f"severity = ${len(params)}")
    if anomaly_type:
        params.append(anomaly_type)
        conditions.append(f"anomaly_type = ${len(params)}")

    params += [limit, offset]
    where = " AND ".join(conditions)

    rows = await db.fetch(f"""
        SELECT al.*,
               COALESCE(at2.action_type, NULL) AS latest_action,
               COALESCE(at2.status, NULL)       AS action_status
        FROM anomaly_logs al
        LEFT JOIN LATERAL (
            SELECT action_type, status FROM actions_taken
            WHERE anomaly_id = al.id ORDER BY executed_at DESC LIMIT 1
        ) at2 ON TRUE
        WHERE {where}
        ORDER BY al.detected_at DESC
        LIMIT ${len(params)-1} OFFSET ${len(params)}
    """, *params)

    return [dict(r) for r in rows]


@router.get("/stats")
async def anomaly_stats(db: asyncpg.Connection = Depends(get_db)):
    """Counts by type and severity — drives dashboard feed badges."""
    by_type = await db.fetch("""
        SELECT anomaly_type, COUNT(*) AS count,
               SUM(cost_impact_inr) AS total_impact
        FROM anomaly_logs
        GROUP BY anomaly_type ORDER BY count DESC
    """)
    by_severity = await db.fetch("""
        SELECT severity, COUNT(*) AS count
        FROM anomaly_logs GROUP BY severity
    """)
    total = await db.fetchval("SELECT COUNT(*) FROM anomaly_logs")
    return {
        "total": total,
        "by_type": [dict(r) for r in by_type],
        "by_severity": [dict(r) for r in by_severity],
    }


@router.get("/{anomaly_id}")
async def get_anomaly(anomaly_id: UUID, db: asyncpg.Connection = Depends(get_db)):
    row = await db.fetchrow("SELECT * FROM anomaly_logs WHERE id = $1", anomaly_id)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    actions = await db.fetch(
        "SELECT * FROM actions_taken WHERE anomaly_id = $1 ORDER BY executed_at DESC",
        anomaly_id,
    )
    return {**dict(row), "actions": [dict(a) for a in actions]}


@router.post("/{anomaly_id}/dismiss")
async def dismiss_anomaly(
    anomaly_id: UUID,
    reason: str = Query(...),
    db: asyncpg.Connection = Depends(get_db),
):
    row = await db.fetchrow("""
        UPDATE anomaly_logs SET status='dismissed', override_reason=$2
        WHERE id=$1 RETURNING id, status
    """, anomaly_id, reason)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return dict(row)


@router.patch("/{anomaly_id}/status")
async def update_anomaly_status(
    anomaly_id: UUID,
    status: str = Query(..., description="New status: active, investigating, dismissed, resolved"),
    db: asyncpg.Connection = Depends(get_db),
):
    """Update anomaly status — used by dashboard for workflow transitions."""
    valid = {"active", "investigating", "dismissed", "resolved"}
    if status not in valid:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid}")
    row = await db.fetchrow("""
        UPDATE anomaly_logs SET status=$2
        WHERE id=$1 RETURNING id, status
    """, anomaly_id, status)
    if not row:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return dict(row)