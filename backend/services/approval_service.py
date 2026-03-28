"""
Approval Service — enterprise-grade governance layer.

Handles:
  1. Auto-approve gate  — actions ≤ ₹50,000 execute immediately
  2. Approval queue     — actions > ₹50,000 wait for human sign-off
  3. Approve / Reject   — human decision triggers or cancels execution
  4. Override flow      — finance team can reverse an already-executed action
  5. Rollback execution — calls the right action_handler to undo the action

Blueprint §8A:
  IF cost_impact > ₹50,000 → require human approval
  ELSE → auto-execute
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from core.config import settings
from core.constants import ActionState, ActionType, AgentName
from core.utils import utcnow, safe_jsonable

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# APPROVAL GATE
# ═══════════════════════════════════════════════════════════════════════════
def requires_approval(cost_impact_inr: float) -> bool:
    """
    Blueprint §8A threshold check.
    Returns True if the action must wait for human approval before execution.
    """
    return cost_impact_inr > settings.AUTO_APPROVE_LIMIT


# ═══════════════════════════════════════════════════════════════════════════
# QUEUE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════
async def enqueue_for_approval(
    db: asyncpg.Connection,
    action_id: UUID,
    anomaly_id: UUID,
    action_type: ActionType,
    cost_impact_inr: float,
    payload: dict,
    rollback_payload: dict,
    executed_by: str,
) -> UUID:
    """
    Move a high-cost action into the approval queue.
    Sets action status → PENDING_APPROVAL.
    """
    await db.execute("""
        UPDATE actions_taken
        SET status = $1, approval_required = TRUE
        WHERE id = $2
    """, ActionState.PENDING_APPROVAL.value, action_id)

    logger.info(
        "Action %s enqueued for approval (cost: ₹%.0f > threshold ₹%.0f)",
        action_id, cost_impact_inr, settings.AUTO_APPROVE_LIMIT,
    )
    return action_id


async def get_pending_approvals(db: asyncpg.Connection) -> list[dict]:
    """Fetch all actions waiting for human approval."""
    rows = await db.fetch("""
        SELECT
            a.id,
            a.action_type,
            a.cost_saved,
            a.executed_by,
            a.executed_at,
            a.payload,
            a.status,
            al.anomaly_type,
            al.severity,
            al.confidence,
            al.reasoning,
            al.root_cause
        FROM actions_taken a
        LEFT JOIN anomaly_logs al ON a.anomaly_id = al.id
        WHERE a.status = $1
        ORDER BY a.executed_at DESC
    """, ActionState.PENDING_APPROVAL.value)
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
# APPROVE
# ═══════════════════════════════════════════════════════════════════════════
async def approve_action(
    db: asyncpg.Connection,
    action_id: UUID,
    approved_by: str,
) -> dict:
    """
    Human approves a pending action.
    Transitions: PENDING_APPROVAL → APPROVED → triggers execution.
    Returns the action record.
    """
    row = await db.fetchrow("""
        UPDATE actions_taken
        SET
            status = $1,
            approved_by = $2,
            approval_timestamp = NOW()
        WHERE id = $3 AND status = $4
        RETURNING *
    """, ActionState.APPROVED.value, approved_by, action_id,
        ActionState.PENDING_APPROVAL.value)

    if not row:
        raise ValueError(f"Action {action_id} not found or not in PENDING_APPROVAL state")

    logger.info("Action %s approved by %s", action_id, approved_by)

    # Trigger execution now that it's approved
    action = dict(row)
    await _execute_approved_action(db, action)
    return action


async def _execute_approved_action(db: asyncpg.Connection, action: dict) -> None:
    """Dispatch to the appropriate action handler after approval."""
    action_type = ActionType(action["action_type"])
    payload = action.get("payload") or {}

    try:
        if action_type == ActionType.PAYMENT_HOLD:
            from action_handlers.payment_handler import hold_payment
            await hold_payment(
                db,
                invoice_id=UUID(payload["invoice_id"]),
                reason=payload.get("reason", "Approved by " + action["approved_by"]),
                amount=float(payload.get("amount", 0)),
                action_id=action["id"],
            )

        elif action_type == ActionType.LICENSE_DEACTIVATED:
            from action_handlers.license_handler import deactivate_license
            await deactivate_license(
                db,
                license_id=UUID(payload["license_id"]),
                action_id=action["id"],
            )

        elif action_type == ActionType.SLA_ESCALATION:
            from action_handlers.sla_handler import escalate_ticket
            await escalate_ticket(
                db,
                ticket_id=payload["ticket_id"],
                action_id=action["id"],
            )

        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.SUCCESS.value, action["id"])

        logger.info("Post-approval execution complete for action %s", action["id"])

    except Exception as exc:
        logger.error("Post-approval execution failed for action %s: %s", action["id"], exc)
        await db.execute("""
            UPDATE actions_taken SET status = $1 WHERE id = $2
        """, ActionState.FAILED.value, action["id"])


# ═══════════════════════════════════════════════════════════════════════════
# REJECT
# ═══════════════════════════════════════════════════════════════════════════
async def reject_action(
    db: asyncpg.Connection,
    action_id: UUID,
    rejected_by: str,
    reason: str,
) -> dict:
    """
    Human rejects a pending action. Action is never executed.
    Transitions: PENDING_APPROVAL → REJECTED.
    """
    row = await db.fetchrow("""
        UPDATE actions_taken
        SET
            status = $1,
            approved_by = $2,
            approval_timestamp = NOW(),
            rejection_reason = $3
        WHERE id = $4 AND status = $5
        RETURNING *
    """, ActionState.REJECTED.value, rejected_by, reason, action_id,
        ActionState.PENDING_APPROVAL.value)

    if not row:
        raise ValueError(f"Action {action_id} not found or not in PENDING_APPROVAL state")

    logger.info("Action %s rejected by %s: %s", action_id, rejected_by, reason)
    return dict(row)


# ═══════════════════════════════════════════════════════════════════════════
# OVERRIDE  (reverse an already-executed action)
# ═══════════════════════════════════════════════════════════════════════════
async def override_action(
    db: asyncpg.Connection,
    action_id: UUID,
    overridden_by: str,
    reason: str,
) -> dict:
    """
    Finance team flags an executed action as a false positive and reverses it.
    Blueprint §11A recovery flow.

    Transitions: SUCCESS → OVERRIDDEN
    Also updates the parent anomaly_log to status=overridden.
    """
    # Fetch the action and its rollback payload
    action_row = await db.fetchrow("""
        SELECT * FROM actions_taken WHERE id = $1 AND status = $2
    """, action_id, ActionState.SUCCESS.value)

    if not action_row:
        raise ValueError(f"Action {action_id} not found or not in SUCCESS state")

    action = dict(action_row)
    rollback_payload = action.get("rollback_payload") or {}

    # Execute rollback
    await _execute_rollback(db, action, rollback_payload)

    # Update action record
    await db.execute("""
        UPDATE actions_taken
        SET
            status = $1,
            rolled_back_at = NOW(),
            rejection_reason = $2,
            approved_by = $3
        WHERE id = $4
    """, ActionState.OVERRIDDEN.value, reason, overridden_by, action_id)

    # Update parent anomaly
    if action.get("anomaly_id"):
        await db.execute("""
            UPDATE anomaly_logs
            SET
                status = 'overridden',
                override_reason = $1,
                overridden_by = $2,
                overridden_at = NOW()
            WHERE id = $3
        """, reason, overridden_by, action["anomaly_id"])

    # Write override audit entry
    await _write_override_audit(db, action, overridden_by, reason)

    logger.info("Action %s overridden by %s: %s", action_id, overridden_by, reason)
    return dict(await db.fetchrow("SELECT * FROM actions_taken WHERE id = $1", action_id))


async def _execute_rollback(
    db: asyncpg.Connection,
    action: dict,
    rollback_payload: dict,
) -> None:
    """Dispatch to the correct handler's rollback method."""
    action_type = ActionType(action["action_type"])

    if action_type == ActionType.PAYMENT_HOLD:
        from action_handlers.payment_handler import release_payment
        invoice_id = rollback_payload.get("invoice_id") or action["payload"]["invoice_id"]
        await release_payment(db, invoice_id=UUID(invoice_id))

    elif action_type == ActionType.LICENSE_DEACTIVATED:
        from action_handlers.license_handler import restore_license
        license_id = rollback_payload.get("license_id") or action["payload"]["license_id"]
        await restore_license(db, license_id=UUID(license_id))

    elif action_type == ActionType.RESOURCE_DOWNSIZE:
        from action_handlers.sla_handler import restore_resource
        await restore_resource(db, rollback_payload=rollback_payload)

    else:
        logger.warning("No rollback handler for action type %s", action_type)


async def _write_override_audit(
    db: asyncpg.Connection,
    action: dict,
    overridden_by: str,
    reason: str,
) -> None:
    """Append an override record to the audit trail (blueprint §11A)."""
    from core.utils import generate_audit_id
    import json

    await db.execute("""
        INSERT INTO audit_trail
            (audit_id, agent, model_used, input_data, final_status, override_reason, reversed_action)
        VALUES ($1, $2, $3, $4, 'overridden', $5, $6)
    """,
        generate_audit_id(),
        AgentName.ACTION.value,
        None,
        json.dumps(safe_jsonable({
            "action_id": str(action["id"]),
            "overridden_by": overridden_by,
        })),
        reason,
        action["action_type"],
    )