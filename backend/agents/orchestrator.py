"""
Orchestrator Agent — blueprint §2B + §2C.

Implements the 10-step data flow:
  1.  Dequeue task from Redis
  2.  Dispatch to AnomalyDetectionAgent
  3.  Score each finding (0.0–1.0 confidence)
  4+5 If HIGH/CRITICAL → invoke DecisionAgent (deepseek-r1)
  6.  Validate action, call ActionExecutionAgent
  7.  ActionAgent performs: email, hold, deactivate, escalate
  8.  AuditAgent logs full trail
  9.  Publish result summary to ci:results
  10. Dashboard polls /api/savings/summary

Also runs the background Redis consumer loop as an asyncio Task.
"""
import asyncio
import logging
from typing import Optional
from uuid import UUID, uuid4

import asyncpg

from agents.action_execution import ActionExecutionAgent
from agents.anomaly_detection import AnomalyDetectionAgent
from agents.audit_agent import AuditAgent
from agents.base_agent import BaseAgent
from agents.decision_agent import DecisionAgent
from agents.fallback_agent import FallbackAgent
from agents.interfaces import (
    ActionResult, DecisionResult, DetectionResult, PipelineResult,
)
from core.constants import (
    AgentName, AnomalyStatus, ModelName, Severity,
)
from core.utils import safe_jsonable, utcnow
from models.schemas import AgentTask

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.ORCHESTRATOR, db)

        # Sub-agents share the same DB connection
        self.anomaly_agent  = AnomalyDetectionAgent(db)
        self.decision_agent = DecisionAgent(db)
        self.action_agent   = ActionExecutionAgent(db)
        self.audit_agent    = AuditAgent(db)
        self.fallback_agent = FallbackAgent(db)

    # ══════════════════════════════════════════════════════════════════════
    # PIPELINE — blueprint §2C 10-step data flow
    # ══════════════════════════════════════════════════════════════════════
    async def run(self, task: AgentTask) -> PipelineResult:
        self._start_timer()
        pipeline = PipelineResult(
            task_id=task.task_id,
            task_type=task.task_type,
            total_elapsed_ms=0,
        )

        try:
            # ── Step 2: Anomaly Detection ──────────────────────────────────
            detections: list[DetectionResult] = await self.anomaly_agent.run(task)
            pipeline.detections = detections
            pipeline.anomalies_detected = len(detections)

            if not detections:
                pipeline.total_elapsed_ms = self._elapsed_ms()
                await self.audit_agent.log(pipeline)
                return pipeline

            # ── Steps 3–7: Decide + Act for each detection ────────────────
            for detection in detections:
                try:
                    # Persist anomaly to DB
                    anomaly_id = await self._persist_anomaly(detection)

                    # Steps 4+5: Route to Decision Agent if HIGH/CRITICAL
                    decision: Optional[DecisionResult] = None
                    if detection.needs_deep_reasoning:
                        decision = await self.decision_agent.reason(
                            detection,
                            extra_context={"task_id": task.task_id},
                        )
                        pipeline.decisions.append(decision)

                        # Update anomaly with reasoning
                        await self._update_anomaly_reasoning(anomaly_id, decision)
                    else:
                        # Build a lightweight decision from detection data alone
                        decision = self._auto_decision(detection)

                    # Step 6+7: Execute action
                    if decision and decision.recommended_action:
                        action = await self.action_agent.execute(decision, anomaly_id)
                        pipeline.actions.append(action)
                        pipeline.actions_taken += 1
                        pipeline.total_cost_saved += action.cost_saved or 0

                        # Update anomaly status
                        await self._update_anomaly_status(anomaly_id, action)

                except Exception as exc:
                    logger.error(
                        "Pipeline error on detection %s: %s",
                        detection.entity_id, exc,
                    )
                    pipeline.errors.append(str(exc))
                    await self.fallback_agent.handle_error(exc, task)

            # ── Step 8: Audit ──────────────────────────────────────────────
            pipeline.total_elapsed_ms = self._elapsed_ms()
            await self.audit_agent.log(pipeline)

            # ── Step 9: Publish result ─────────────────────────────────────
            try:
                from services.redis_client import publish_result
                await publish_result(pipeline.to_summary())
            except Exception:
                pass  # Non-critical — dashboard will poll DB directly

            self.logger.info(
                "Pipeline complete — task=%s | detections=%d | actions=%d | "
                "cost=₹%.0f | elapsed=%.0fms",
                task.task_id,
                pipeline.anomalies_detected,
                pipeline.actions_taken,
                float(pipeline.total_cost_saved),
                pipeline.total_elapsed_ms,
            )

        except Exception as exc:
            pipeline.errors.append(str(exc))
            pipeline.total_elapsed_ms = self._elapsed_ms()
            logger.error("Orchestrator pipeline failed: %s", exc)
            await self.fallback_agent.handle_error(exc, task)

        return pipeline

    # ══════════════════════════════════════════════════════════════════════
    # BACKGROUND CONSUMER LOOP
    # ══════════════════════════════════════════════════════════════════════
    async def consume_forever(self) -> None:
        """
        Background asyncio Task — consumes Redis queue continuously.
        Gets a fresh DB connection for each task to avoid connection reuse issues.
        """
        from services.redis_client import consume_tasks
        from db.database import get_pool

        logger.info("Orchestrator consumer loop started")

        async for task in consume_tasks():
            try:
                # Fresh connection per task (avoids stale transaction state)
                async with get_pool().acquire() as conn:
                    orch = OrchestratorAgent(conn)
                    await orch.run(task)
            except Exception as exc:
                logger.error("Consumer loop error on task %s: %s", task.task_id, exc)
            finally:
                await asyncio.sleep(0)  # Yield to event loop

    # ══════════════════════════════════════════════════════════════════════
    # DB HELPERS
    # ══════════════════════════════════════════════════════════════════════
    async def _persist_anomaly(self, detection: DetectionResult) -> UUID:
        """Write detection to anomaly_logs. Returns anomaly UUID."""
        import json
        row = await self.db.fetchrow("""
            INSERT INTO anomaly_logs (
                anomaly_type, entity_id, entity_table, confidence,
                severity, cost_impact_inr, status, model_used
            ) VALUES ($1, $2, $3, $4, $5, $6, 'detected', $7)
            RETURNING id
        """,
            detection.anomaly_type.value,
            detection.entity_id,
            detection.entity_table,
            detection.confidence,
            detection.severity.value if detection.severity else "MEDIUM",
            float(detection.cost_impact_inr),
            detection.model_used.value if detection.model_used else None,
        )
        return row["id"]

    async def _update_anomaly_reasoning(
        self, anomaly_id: UUID, decision: DecisionResult
    ) -> None:
        import json
        await self.db.execute("""
            UPDATE anomaly_logs
            SET reasoning = $2, root_cause = $3, model_used = $4
            WHERE id = $1
        """,
            anomaly_id,
            json.dumps(safe_jsonable(decision.reasoning_chain)),
            decision.root_cause,
            decision.model_used.value if decision.model_used else None,
        )

    async def _update_anomaly_status(
        self, anomaly_id: UUID, action: ActionResult
    ) -> None:
        status = (
            AnomalyStatus.ACTIONED.value
            if action.success and not action.approval_required
            else "pending_approval" if action.approval_required
            else AnomalyStatus.DETECTED.value
        )
        await self.db.execute(
            "UPDATE anomaly_logs SET status=$2 WHERE id=$1",
            anomaly_id, status,
        )

    def _auto_decision(self, detection: DetectionResult) -> DecisionResult:
        """
        For LOW/MEDIUM severity — skip deepseek, map detection directly to action.
        """
        from core.constants import ActionType, AnomalyType

        action_map = {
            AnomalyType.DUPLICATE_PAYMENT:   ActionType.PAYMENT_HOLD,
            AnomalyType.UNUSED_SUBSCRIPTION: ActionType.LICENSE_DEACTIVATED,
            AnomalyType.SLA_RISK:            ActionType.SLA_ESCALATION,
            AnomalyType.PRICING_ANOMALY:     ActionType.VENDOR_RENEGOTIATION_FLAG,
            AnomalyType.RECONCILIATION_GAP:  ActionType.EMAIL_SENT,
            AnomalyType.INFRA_WASTE:         ActionType.RESOURCE_DOWNSIZE,
        }

        action = action_map.get(detection.anomaly_type, ActionType.EMAIL_SENT)

        return DecisionResult(
            agent=AgentName.ORCHESTRATOR,
            model_used=ModelName.QWEN,
            elapsed_ms=0,
            success=True,
            root_cause=f"Auto-decision: {detection.anomaly_type.value} detected "
                       f"with confidence {detection.confidence:.0%}",
            recommended_action=action,
            action_details=detection.evidence,
            confidence=detection.confidence,
            cost_impact_inr=detection.cost_impact_inr,
            urgency=detection.severity,
            reasoning_chain=[
                f"Step 1: {detection.anomaly_type.value} detected",
                f"Step 2: Confidence {detection.confidence:.0%} — auto-action threshold met",
                f"Step 3: Applying default action: {action.value}",
            ],
        )