"""
SLA Handler — escalate, reroute, and close SLA tickets.
Also handles resource downsize/restore stubs for infrastructure waste.

Blueprint §8:
  - sla_escalation: POST /api/tickets/{id}/escalate
  - resource_downsize: PATCH /api/resources/{id}/resize
"""
import logging
from uuid import UUID
from typing import Optional

import asyncpg

from core.constants import ActionState
from core.utils import utcnow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# SLA ESCALATION
# ═══════════════════════════════════════════════════════════════════════════
async def escalate_ticket(
    db: asyncpg.Connection,
    ticket_id: str,
    action_id: Optional[UUID] = None,
    escalated_to: Optional[str] = None,
) -> dict:
    """
    Mark an SLA ticket as escalated.
    Blueprint §3 Agent 2: escalate to Team Lead when P(breach) > 0.70.
    """
    row = await db.fetchrow("""
        UPDATE sla_metrics
        SET
            status       = 'escalated',
            escalated_at = NOW()
        WHERE ticket_id = $1 AND status = 'open'
        RETURNING id, ticket_id, sla_hours, priority, penalty_amount,
                  breach_prob, escalated_at
    """, ticket_id)

    if not row:
        raise ValueError(f"Ticket {ticket_id} not found or not in 'open' state")

    logger.info(
        "Ticket ESCALATED — %s | P(breach)=%.2f | penalty ₹%.0f%s",
        row["ticket_id"],
        float(row["breach_prob"]),
        float(row["penalty_amount"]),
        f" → {escalated_to}" if escalated_to else "",
    )

    if action_id:
        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.SUCCESS.value, action_id)

    return dict(row)


async def reroute_ticket(
    db: asyncpg.Connection,
    ticket_id: str,
    new_assignee_id: UUID,
    action_id: Optional[UUID] = None,
) -> dict:
    """
    Assign ticket to a new agent to prevent SLA breach.
    Blueprint §3 Agent 2: 'Reroute to next available L2 agent.'
    """
    row = await db.fetchrow("""
        UPDATE sla_metrics
        SET assignee_id = $2
        WHERE ticket_id = $1
        RETURNING id, ticket_id, assignee_id
    """, ticket_id, new_assignee_id)

    if not row:
        raise ValueError(f"Ticket {ticket_id} not found")

    logger.info("Ticket REROUTED — %s → assignee %s", row["ticket_id"], row["assignee_id"])
    return dict(row)


async def close_ticket(
    db: asyncpg.Connection,
    ticket_id: str,
    resolved_by: str = "system",
) -> dict:
    """Mark a ticket as resolved."""
    row = await db.fetchrow("""
        UPDATE sla_metrics
        SET status = 'resolved', resolved_at = NOW()
        WHERE ticket_id = $1
        RETURNING id, ticket_id, status, resolved_at, penalty_amount
    """, ticket_id)

    if not row:
        raise ValueError(f"Ticket {ticket_id} not found")

    logger.info("Ticket RESOLVED — %s by %s", row["ticket_id"], resolved_by)
    return dict(row)


async def update_breach_probability(
    db: asyncpg.Connection,
    ticket_id: str,
    breach_prob: float,
) -> None:
    """Update the breach probability stored on the ticket (called by SLA agent)."""
    await db.execute("""
        UPDATE sla_metrics SET breach_prob = $2 WHERE ticket_id = $1
    """, ticket_id, breach_prob)


async def get_at_risk_tickets(
    db: asyncpg.Connection,
    threshold: float = 0.70,
) -> list[dict]:
    """
    Return all open tickets above the breach probability threshold.
    Called by APScheduler every 15 minutes.
    """
    rows = await db.fetch("""
        SELECT
            id, ticket_id, sla_hours, opened_at, sla_deadline,
            status, assignee_id, priority, penalty_amount, breach_prob,
            EXTRACT(EPOCH FROM (NOW() - opened_at)) / 3600 AS elapsed_hours
        FROM sla_metrics
        WHERE status = 'open'
        ORDER BY breach_prob DESC, sla_deadline ASC
    """)
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
# RESOURCE DOWNSIZE (infrastructure waste — stub for demo)
# ═══════════════════════════════════════════════════════════════════════════
async def downsize_resource(
    db: asyncpg.Connection,
    resource_id: str,
    current_size: str,
    target_size: str,
    action_id: Optional[UUID] = None,
) -> dict:
    """
    Mock resource downsize action.
    In production this would call cloud provider APIs (AWS/GCP/Azure).
    Blueprint §8: PATCH /api/resources/{id}/resize
    """
    logger.info(
        "Resource DOWNSIZED — %s: %s → %s [MOCK]",
        resource_id, current_size, target_size,
    )

    result = {
        "resource_id": resource_id,
        "previous_size": current_size,
        "new_size": target_size,
        "status": "downsized",
        "note": "Mock action — integrate cloud provider API for production",
    }

    if action_id:
        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.SUCCESS.value, action_id)

    return result


async def restore_resource(
    db: asyncpg.Connection,
    rollback_payload: dict,
) -> dict:
    """Restore resource to previous size (rollback)."""
    resource_id = rollback_payload.get("resource_id")
    previous_size = rollback_payload.get("previous_size")

    logger.info("Resource RESTORED — %s → %s [MOCK]", resource_id, previous_size)
    return {
        "resource_id": resource_id,
        "restored_size": previous_size,
        "status": "restored",
    }