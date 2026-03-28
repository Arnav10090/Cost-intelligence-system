"""
Payment Handler — hold, release, and rollback payment actions.

Blueprint §8:
  - payment_hold: UPDATE transactions SET status='held'
  - Rollback: restore status to 'pending' or 'approved'
  - Auto-release after 48h if not confirmed (handled by scheduler)
"""
import logging
from uuid import UUID
from typing import Optional

import asyncpg

from core.constants import ActionState
from core.utils import utcnow

logger = logging.getLogger(__name__)


async def hold_payment(
    db: asyncpg.Connection,
    invoice_id: UUID,
    reason: str,
    amount: float,
    action_id: Optional[UUID] = None,
) -> dict:
    """
    Place a hold on a transaction.
    Blueprint §8: UPDATE transactions SET status='held'

    Returns the updated transaction row.
    """
    row = await db.fetchrow("""
        UPDATE transactions
        SET
            status      = 'held',
            hold_reason = $2,
            updated_at  = NOW()
        WHERE id = $1
        RETURNING id, status, hold_reason, amount, vendor_id, invoice_number
    """, invoice_id, reason)

    if not row:
        raise ValueError(f"Transaction {invoice_id} not found")

    logger.info(
        "Payment HELD — invoice %s | amount ₹%.0f | reason: %s",
        row["invoice_number"], amount, reason,
    )

    # Update action record status if provided
    if action_id:
        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.SUCCESS.value, action_id)

    return dict(row)


async def release_payment(
    db: asyncpg.Connection,
    invoice_id: UUID,
    released_by: str = "system",
) -> dict:
    """
    Release a held payment back to 'approved'.
    Used for: rollback after override, auto-release after 48h.
    """
    row = await db.fetchrow("""
        UPDATE transactions
        SET
            status      = 'approved',
            hold_reason = NULL,
            updated_at  = NOW()
        WHERE id = $1 AND status = 'held'
        RETURNING id, status, invoice_number
    """, invoice_id)

    if not row:
        raise ValueError(f"Transaction {invoice_id} not found or not in 'held' state")

    logger.info(
        "Payment RELEASED — invoice %s by %s",
        row["invoice_number"], released_by,
    )
    return dict(row)


async def auto_release_stale_holds(db: asyncpg.Connection) -> int:
    """
    Release payments held > AUTO_RELEASE_HOURS with no approval confirmation.
    Called by APScheduler. Blueprint §8: auto-release in 48h if no confirmation.

    Returns count of released transactions.
    """
    from core.config import settings

    rows = await db.fetch("""
        UPDATE transactions
        SET status = 'pending', hold_reason = hold_reason || ' [auto-released]', updated_at = NOW()
        WHERE
            status = 'held'
            AND updated_at < NOW() - ($1 * INTERVAL '1 hour')
        RETURNING id, invoice_number
    """, settings.PAYMENT_HOLD_AUTO_RELEASE_HOURS)

    if rows:
        logger.info("Auto-released %d stale payment holds", len(rows))

    return len(rows)