"""
Audit Agent — blueprint §10.

Writes an immutable audit record after every pipeline run.
The audit trail is the compliance backbone and demo differentiator:
every decision is logged with input → detection → reasoning → action → impact.
"""
import json
import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from agents.base_agent import BaseAgent
from agents.interfaces import PipelineResult
from core.constants import AgentName, ModelName
from core.utils import generate_audit_id, safe_jsonable
from models.schemas import AgentTask

logger = logging.getLogger(__name__)


class AuditAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.AUDIT, db)

    async def run(self, task: AgentTask):
        pass  # Called via log() not run()

    async def log(self, pipeline_result: PipelineResult) -> str:
        """
        Write one audit_trail record per pipeline run.
        Returns the audit_id (e.g. aud-20240115-001).
        Blueprint §10 schema: all fields preserved.
        """
        self._start_timer()
        audit_id = generate_audit_id()

        # Aggregate across all pipeline stages
        total_cost = sum(
            a.cost_saved for a in pipeline_result.actions
            if a.cost_saved
        )
        reasoning_invoked = any(
            d.model_used == ModelName.DEEPSEEK
            for d in pipeline_result.decisions
        )
        reasoning_model = (
            ModelName.DEEPSEEK.value if reasoning_invoked else None
        )
        reasoning_output = (
            [d.to_audit_dict() for d in pipeline_result.decisions]
            if reasoning_invoked else None
        )

        # Primary detection and action for the record
        primary_detection = pipeline_result.detections[0] if pipeline_result.detections else None
        primary_action    = pipeline_result.actions[0]    if pipeline_result.actions    else None

        # Approval status
        approval_status = None
        if primary_action and primary_action.approval_required:
            approval_status = "pending_approval"
        elif primary_action and primary_action.success:
            approval_status = "auto_approved"

        final_status = "actioned" if pipeline_result.actions else "detected_no_action"
        if pipeline_result.errors:
            final_status = "partial_error"

        try:
            await self.db.execute("""
                INSERT INTO audit_trail (
                    audit_id, agent, model_used,
                    input_data, detection,
                    reasoning_invoked, reasoning_model, reasoning_output,
                    action_taken, cost_impact_inr,
                    approval_status, final_status
                ) VALUES (
                    $1, $2, $3,
                    $4::jsonb, $5::jsonb,
                    $6, $7, $8::jsonb,
                    $9::jsonb, $10,
                    $11, $12
                )
            """,
                audit_id,
                AgentName.AUDIT.value,
                reasoning_model or (ModelName.QWEN.value),

                json.dumps(safe_jsonable({
                    "task_id": pipeline_result.task_id,
                    "task_type": pipeline_result.task_type,
                    "total_elapsed_ms": pipeline_result.total_elapsed_ms,
                })),

                json.dumps(safe_jsonable(
                    primary_detection.to_audit_dict() if primary_detection else {}
                )),

                reasoning_invoked,
                reasoning_model,
                json.dumps(safe_jsonable(reasoning_output)) if reasoning_output else None,

                json.dumps(safe_jsonable(
                    primary_action.to_audit_dict() if primary_action else {}
                )),

                float(total_cost),
                approval_status,
                final_status,
            )

            self.logger.info(
                "Audit written: %s | cost=₹%.0f | status=%s (%.0fms)",
                audit_id, float(total_cost), final_status, self._elapsed_ms(),
            )

        except Exception as exc:
            self.logger.error("Audit write failed: %s", exc)

        return audit_id

    async def get_trail(
        self,
        db: asyncpg.Connection,
        limit: int = 50,
        type_filter: Optional[str] = None,
        offset: int = 0,
    ) -> list[dict]:
        if type_filter:
            rows = await db.fetch("""
                SELECT * FROM audit_trail
                WHERE final_status = $1
                ORDER BY timestamp DESC
                LIMIT $2 OFFSET $3
            """, type_filter, limit, offset)
        else:
            rows = await db.fetch("""
                SELECT * FROM audit_trail
                ORDER BY timestamp DESC
                LIMIT $1 OFFSET $2
            """, limit, offset)
        return [dict(r) for r in rows]

    async def get_record(self, db: asyncpg.Connection, audit_id: str) -> Optional[dict]:
        row = await db.fetchrow(
            "SELECT * FROM audit_trail WHERE audit_id = $1", audit_id
        )
        return dict(row) if row else None

    async def get_summary(self, db: asyncpg.Connection, period: str = "month") -> dict:
        interval = "30 days" if period == "month" else "7 days"
        row = await db.fetchrow(f"""
            SELECT
                COUNT(*)                                     AS total_audits,
                SUM(cost_impact_inr)                         AS total_cost_impact,
                COUNT(*) FILTER (WHERE reasoning_invoked)    AS deepseek_invocations,
                COUNT(*) FILTER (WHERE final_status='actioned') AS actioned_count,
                COUNT(*) FILTER (WHERE approval_status='pending_approval') AS pending_count
            FROM audit_trail
            WHERE timestamp > NOW() - INTERVAL '{interval}'
        """)
        return dict(row) if row else {}