"""
Action Execution Agent — blueprint §8.

Receives a DecisionResult, checks the approval gate, and dispatches
to the appropriate action_handler. Persists every action to actions_taken
with a rollback_payload so the override flow can reverse it.

Blueprint §8A: IF cost_impact > ₹50,000 → require human approval ELSE auto-execute.
"""
import json
import logging
import uuid
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from agents.base_agent import BaseAgent
from agents.interfaces import ActionResult, DecisionResult
from core.constants import ActionState, ActionType, AgentName, ModelName
from core.utils import safe_jsonable
from models.schemas import AgentTask
from services.approval_service import requires_approval, enqueue_for_approval

logger = logging.getLogger(__name__)


class ActionExecutionAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.ACTION, db)

    async def run(self, task: AgentTask) -> ActionResult:
        """Not used directly — call execute() with a DecisionResult."""
        return ActionResult(
            agent=self.name, model_used=None,
            elapsed_ms=0, success=False,
            error="Use execute() method directly",
        )

    async def execute(
        self,
        decision: DecisionResult,
        anomaly_id: UUID,
    ) -> ActionResult:
        """
        Main entry point. Checks approval gate, dispatches action, persists result.
        """
        self._start_timer()

        if not decision.recommended_action:
            return ActionResult(
                agent=self.name, model_used=decision.model_used,
                elapsed_ms=self._elapsed_ms(), success=True,
                action_type=None, action_state=ActionState.SUCCESS,
                anomaly_id=anomaly_id,
            )

        cost = float(decision.cost_impact_inr)
        needs_approval = requires_approval(cost)

        # ── Persist action record ──────────────────────────────────────────
        action_id = await self._persist_action(
            anomaly_id=anomaly_id,
            action_type=decision.recommended_action,
            cost_saved=decision.cost_impact_inr,
            approval_required=needs_approval,
            payload=decision.action_details,
            model_used=decision.model_used,
        )

        # ── Approval gate ──────────────────────────────────────────────────
        if needs_approval:
            await enqueue_for_approval(
                self.db, action_id, anomaly_id,
                decision.recommended_action,
                cost,
                decision.action_details,
                self._build_rollback_payload(decision),
                AgentName.ACTION.value,
            )
            self.logger.info(
                "Action %s queued for approval — cost ₹%.0f > limit ₹%.0f",
                decision.recommended_action.value, cost,
                __import__("core.config", fromlist=["settings"]).settings.AUTO_APPROVE_LIMIT,
            )
            return ActionResult(
                agent=self.name, model_used=decision.model_used,
                elapsed_ms=self._elapsed_ms(), success=True,
                action_type=decision.recommended_action,
                action_state=ActionState.PENDING_APPROVAL,
                cost_saved=decision.cost_impact_inr,
                anomaly_id=anomaly_id,
                approval_required=True,
                approval_request_id=action_id,
            )

        # ── Auto-execute ───────────────────────────────────────────────────
        result = await self._dispatch(
            action_type=decision.recommended_action,
            action_details=decision.action_details,
            action_id=action_id,
            anomaly_id=anomaly_id,
            decision=decision,
        )

        # Update action record status
        await self.db.execute(
            "UPDATE actions_taken SET status=$1 WHERE id=$2",
            result.action_state.value, action_id,
        )
        
        # Publish action_executed event (Requirement 7.3)
        if result.success and result.action_state == ActionState.SUCCESS:
            try:
                from services.event_broadcaster import EventBroadcaster
                action_row = await self.db.fetchrow(
                    "SELECT * FROM actions_taken WHERE id=$1", action_id
                )
                await EventBroadcaster.publish_action_executed(
                    dict(action_row), anomaly_id=anomaly_id
                )
            except Exception as exc:
                logger.warning("Failed to publish action_executed event: %s", exc)

        return result

    # ── Dispatch table ─────────────────────────────────────────────────────
    async def _dispatch(
        self,
        action_type: ActionType,
        action_details: dict,
        action_id: UUID,
        anomaly_id: UUID,
        decision: DecisionResult,
    ) -> ActionResult:
        try:
            if action_type == ActionType.PAYMENT_HOLD:
                return await self._hold_payment(action_details, action_id, anomaly_id, decision)

            elif action_type == ActionType.LICENSE_DEACTIVATED:
                return await self._deactivate_license(action_details, action_id, anomaly_id, decision)

            elif action_type == ActionType.SLA_ESCALATION:
                return await self._escalate_sla(action_details, action_id, anomaly_id, decision)

            elif action_type == ActionType.VENDOR_RENEGOTIATION_FLAG:
                return await self._flag_vendor(action_details, action_id, anomaly_id, decision)

            elif action_type == ActionType.EMAIL_SENT:
                return await self._send_notification(action_details, action_id, anomaly_id, decision)

            else:
                self.logger.warning("No handler for action type: %s", action_type)
                return self._success_result(action_type, decision, anomaly_id, action_id)

        except Exception as exc:
            self.logger.error("Action dispatch failed for %s: %s", action_type, exc)
            return ActionResult(
                agent=self.name, model_used=decision.model_used,
                elapsed_ms=self._elapsed_ms(), success=False,
                action_type=action_type,
                action_state=ActionState.FAILED,
                cost_saved=Decimal("0"),
                anomaly_id=anomaly_id,
                error=str(exc),
            )

    async def _hold_payment(self, details, action_id, anomaly_id, decision):
        from action_handlers.payment_handler import hold_payment
        from action_handlers.notification_handler import notify_duplicate_payment

        invoice_id = details.get("invoice_id") or str(decision.action_details.get("duplicate_id", ""))
        if not invoice_id:
            raise ValueError("No invoice_id in action_details for payment_hold")

        await hold_payment(
            self.db,
            invoice_id=UUID(invoice_id),
            reason=decision.root_cause or "Duplicate payment detected",
            amount=float(decision.cost_impact_inr),
            action_id=action_id,
        )

        # Send email notification
        ev = decision.action_details
        await notify_duplicate_payment(
            vendor_name=ev.get("vendor_name", "Unknown"),
            invoice_number=ev.get("duplicate_invoice", invoice_id),
            amount=float(decision.cost_impact_inr),
            po_number=ev.get("po_number", ""),
            confidence=decision.confidence,
            reasoning=decision.root_cause,
            anomaly_id=str(anomaly_id),
        )

        return self._success_result(
            ActionType.PAYMENT_HOLD, decision, anomaly_id, action_id,
            rollback={"invoice_id": invoice_id},
        )

    async def _deactivate_license(self, details, action_id, anomaly_id, decision):
        from action_handlers.license_handler import deactivate_license

        license_id = details.get("license_id") or decision.action_details.get("license_id", "")
        if not license_id:
            raise ValueError("No license_id for license_deactivated action")

        await deactivate_license(
            self.db,
            license_id=UUID(license_id),
            action_id=action_id,
        )

        return self._success_result(
            ActionType.LICENSE_DEACTIVATED, decision, anomaly_id, action_id,
            rollback={"license_id": license_id},
        )

    async def _escalate_sla(self, details, action_id, anomaly_id, decision):
        from action_handlers.sla_handler import escalate_ticket
        from action_handlers.notification_handler import notify_sla_escalation

        ticket_id = details.get("ticket_id") or decision.action_details.get("ticket_id", "")
        if not ticket_id:
            raise ValueError("No ticket_id for sla_escalation action")

        await escalate_ticket(self.db, ticket_id=ticket_id, action_id=action_id)

        ev = decision.action_details
        await notify_sla_escalation(
            ticket_id=ticket_id,
            priority=ev.get("priority", "P2"),
            sla_hours=ev.get("sla_hours", 0),
            elapsed_hours=ev.get("elapsed_hours", 0),
            breach_prob=ev.get("breach_probability", 0),
            penalty_amount=float(decision.cost_impact_inr),
        )

        return self._success_result(
            ActionType.SLA_ESCALATION, decision, anomaly_id, action_id,
            rollback={"ticket_id": ticket_id},
        )

    async def _flag_vendor(self, details, action_id, anomaly_id, decision):
        """Insert a vendor renegotiation task into the DB."""
        await self.db.execute("""
            INSERT INTO anomaly_logs
                (anomaly_type, entity_id, entity_table, confidence, severity,
                 cost_impact_inr, status, model_used, root_cause)
            VALUES ('pricing_anomaly', $1, 'vendors', $2, $3, $4,
                    'actioned', $5, $6)
        """,
            details.get("vendor_id"),
            decision.confidence,
            decision.urgency.value if decision.urgency else "MEDIUM",
            float(decision.cost_impact_inr),
            decision.model_used.value if decision.model_used else None,
            decision.root_cause,
        )
        return self._success_result(
            ActionType.VENDOR_RENEGOTIATION_FLAG, decision, anomaly_id, action_id,
        )

    async def _send_notification(self, details, action_id, anomaly_id, decision):
        from action_handlers.notification_handler import send_alert_email
        from core.config import settings

        anomaly_type = details.get("anomaly_type", "unknown")
        await send_alert_email(
            to=[settings.ALERT_EMAIL],
            anomaly_type=anomaly_type,
            context={**details, "cost_impact": float(decision.cost_impact_inr)},
        )
        return self._success_result(ActionType.EMAIL_SENT, decision, anomaly_id, action_id)

    # ── Helpers ────────────────────────────────────────────────────────────
    def _success_result(
        self,
        action_type: ActionType,
        decision: DecisionResult,
        anomaly_id: UUID,
        action_id: UUID,
        rollback: Optional[dict] = None,
    ) -> ActionResult:
        return ActionResult(
            agent=self.name,
            model_used=decision.model_used,
            elapsed_ms=self._elapsed_ms(),
            success=True,
            action_type=action_type,
            action_state=ActionState.SUCCESS,
            cost_saved=decision.cost_impact_inr,
            anomaly_id=anomaly_id,
            rollback_payload=rollback or {},
            execution_payload=decision.action_details,
        )

    def _build_rollback_payload(self, decision: DecisionResult) -> dict:
        return {
            "action_type": decision.recommended_action.value if decision.recommended_action else None,
            **decision.action_details,
        }

    async def _persist_action(
        self,
        anomaly_id: UUID,
        action_type: ActionType,
        cost_saved: Decimal,
        approval_required: bool,
        payload: dict,
        model_used: Optional[ModelName],
    ) -> UUID:
        rollback = self._build_rollback_payload_from_details(action_type, payload)
        row = await self.db.fetchrow("""
            INSERT INTO actions_taken
                (id, anomaly_id, action_type, executed_by, cost_saved,
                 status, approval_required, payload, rollback_payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb)
            RETURNING id
        """,
            uuid.uuid4(), anomaly_id,
            action_type.value, AgentName.ACTION.value,
            float(cost_saved),
            ActionState.PENDING_APPROVAL.value if approval_required else ActionState.PENDING.value,
            approval_required,
            json.dumps(safe_jsonable(payload)),
            json.dumps(safe_jsonable(rollback)),
        )
        return row["id"]

    @staticmethod
    def _build_rollback_payload_from_details(action_type: ActionType, details: dict) -> dict:
        """Build a rollback payload from action details for persistence."""
        rollback = {"action_type": action_type.value}
        if action_type == ActionType.PAYMENT_HOLD:
            rollback["invoice_id"] = details.get("invoice_id") or details.get("duplicate_id", "")
        elif action_type == ActionType.LICENSE_DEACTIVATED:
            rollback["license_id"] = details.get("license_id", "")
        elif action_type == ActionType.SLA_ESCALATION:
            rollback["ticket_id"] = details.get("ticket_id", "")
        return rollback
