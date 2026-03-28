"""
Fallback Agent — blueprint §2B.

Used when any other agent raises an exception or times out.
Always uses llama3.2:3b. Never propagates exceptions — the pipeline
must always complete so the audit trail remains intact.
"""
import logging

import asyncpg

from agents.base_agent import BaseAgent
from agents.interfaces import AgentResult
from core.constants import AgentName, ModelName, Severity
from models.schemas import AgentTask

logger = logging.getLogger(__name__)


class FallbackAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.FALLBACK, db)

    async def run(self, task: AgentTask) -> AgentResult:
        return await self.handle_error(
            Exception(f"FallbackAgent.run() called — task: {task.task_type}"),
            task,
        )

    async def handle_error(
        self,
        error: Exception,
        task: AgentTask,
    ) -> AgentResult:
        """
        Blueprint §2B: Failure recovery, low-latency response on error or timeout.
        Logs the error, writes a minimal audit record, returns safe failure result.
        """
        self._start_timer()
        self.logger.error(
            "Pipeline error on task %s (%s): %s",
            task.task_id, task.task_type, error,
        )

        # Attempt a brief LLM call for error summary (best-effort)
        error_summary = str(error)
        try:
            text, _ = await self._infer(
                f"Summarize this pipeline error in one sentence: {error}",
                error_state=True,
                is_trivial=True,
            )
            error_summary = text[:200]
        except Exception:
            pass  # Fallback to raw error string

        # Write minimal audit record
        try:
            from core.utils import generate_audit_id
            import json
            audit_id = generate_audit_id()
            await self.db.execute("""
                INSERT INTO audit_trail
                    (audit_id, agent, model_used, input_data, final_status)
                VALUES ($1, $2, $3, $4::jsonb, 'error')
            """,
                audit_id,
                AgentName.FALLBACK.value,
                ModelName.LLAMA.value,
                json.dumps({
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "error": error_summary,
                }),
            )
        except Exception as audit_err:
            self.logger.error("Fallback audit write also failed: %s", audit_err)

        return AgentResult(
            agent=self.name,
            model_used=ModelName.LLAMA,
            elapsed_ms=self._elapsed_ms(),
            success=False,
            error=error_summary,
        )