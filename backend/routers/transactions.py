"""
Transactions router — CRUD + status management for financial transactions.

Endpoints:
  GET  /api/transactions/          — list transactions (filterable)
  GET  /api/transactions/summary   — aggregate stats for dashboard
  GET  /api/transactions/{id}      — single transaction detail
  POST /api/transactions/          — create a new transaction
  PATCH /api/transactions/{id}/hold — place a payment hold
  PATCH /api/transactions/{id}/release — release a held payment

Blueprint §6 + §7.
"""
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db.database import get_db
from models.schemas import TransactionCreate, Transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


# ─── Request bodies ────────────────────────────────────────────────────────
class HoldRequest(BaseModel):
    reason: str


class ReleaseRequest(BaseModel):
    released_by: str = "system"


# ─── Endpoints ────────────────────────────────────────────────────────────

@router.get("/")
async def list_transactions(
    status: Optional[str] = Query(None, description="Filter by status"),
    vendor_id: Optional[UUID] = Query(None, description="Filter by vendor"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: asyncpg.Connection = Depends(get_db),
):
    """List transactions with optional filters. Drives the main transaction table."""
    conditions = []
    params = []
    idx = 1

    if status:
        conditions.append(f"t.status = ${idx}")
        params.append(status)
        idx += 1
    if vendor_id:
        conditions.append(f"t.vendor_id = ${idx}")
        params.append(vendor_id)
        idx += 1
    if date_from:
        conditions.append(f"t.transaction_date >= ${idx}")
        params.append(date_from)
        idx += 1
    if date_to:
        conditions.append(f"t.transaction_date <= ${idx}")
        params.append(date_to)
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT t.*, v.name AS vendor_name
        FROM transactions t
        LEFT JOIN vendors v ON t.vendor_id = v.id
        {where}
        ORDER BY t.transaction_date DESC, t.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit, offset])

    rows = await db.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/summary")
async def transaction_summary(db: asyncpg.Connection = Depends(get_db)):
    """Aggregate transaction stats for the dashboard header."""
    row = await db.fetchrow("""
        SELECT
            COUNT(*)                                    AS total_count,
            COALESCE(SUM(amount), 0)                    AS total_amount,
            COUNT(*) FILTER (WHERE status = 'held')     AS held_count,
            COALESCE(SUM(amount) FILTER (WHERE status = 'held'), 0) AS held_amount,
            COUNT(*) FILTER (WHERE status = 'pending')  AS pending_count,
            COUNT(*) FILTER (WHERE status = 'approved') AS approved_count,
            COUNT(*) FILTER (WHERE status = 'disputed') AS disputed_count
        FROM transactions
    """)
    return dict(row)


@router.get("/{txn_id}")
async def get_transaction(
    txn_id: UUID,
    db: asyncpg.Connection = Depends(get_db),
):
    """Full detail for a single transaction including vendor info."""
    row = await db.fetchrow("""
        SELECT t.*, v.name AS vendor_name, v.category AS vendor_category
        FROM transactions t
        LEFT JOIN vendors v ON t.vendor_id = v.id
        WHERE t.id = $1
    """, txn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return dict(row)


@router.post("/", status_code=201)
async def create_transaction(
    body: TransactionCreate,
    db: asyncpg.Connection = Depends(get_db),
):
    """Insert a new transaction record."""
    row = await db.fetchrow("""
        INSERT INTO transactions (vendor_id, invoice_number, amount, currency, transaction_date, po_number)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
    """, body.vendor_id, body.invoice_number, body.amount,
        body.currency, body.transaction_date, body.po_number)
    return dict(row)


@router.patch("/{txn_id}/hold")
async def hold_transaction(
    txn_id: UUID,
    body: HoldRequest,
    db: asyncpg.Connection = Depends(get_db),
):
    """Place a payment hold on a transaction (used by anomaly actions)."""
    row = await db.fetchrow("""
        UPDATE transactions
        SET status = 'held', hold_reason = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING *
    """, txn_id, body.reason)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Payment held", "transaction": dict(row)}


@router.patch("/{txn_id}/release")
async def release_transaction(
    txn_id: UUID,
    body: ReleaseRequest,
    db: asyncpg.Connection = Depends(get_db),
):
    """Release a held payment (used by override / false-positive recovery)."""
    row = await db.fetchrow("""
        UPDATE transactions
        SET status = 'approved', hold_reason = NULL, updated_at = NOW()
        WHERE id = $1 AND status = 'held'
        RETURNING *
    """, txn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found or not held")
    return {"message": f"Payment released by {body.released_by}", "transaction": dict(row)}
