"""
BaseAgent — abstract base class for all agents.

Every agent inherits:
  - _infer()     : wraps llm_router.infer() with timing
  - _elapsed_ms(): precise elapsed time
  - Consistent logging format: [AgentName] message
"""
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import asyncpg

from agents.interfaces import AgentResult
from core.constants import AgentName, ModelName, Severity
from models.schemas import AgentTask

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(
        self,
        name: AgentName,
        db: Optional[asyncpg.Connection] = None,
    ):
        self.name = name
        self.db = db
        self._start_time: float = 0.0
        self.logger = logging.getLogger(f"agents.{name.value}")

    # ── Abstract interface ─────────────────────────────────────────────────
    @abstractmethod
    async def run(self, task: AgentTask) -> AgentResult:
        """Execute the agent's primary task. Must be implemented by subclass."""
        ...

    # ── Timing ────────────────────────────────────────────────────────────
    def _start_timer(self) -> None:
        self._start_time = time.perf_counter()

    def _elapsed_ms(self) -> float:
        return (time.perf_counter() - self._start_time) * 1000

    # ── LLM inference wrapper ─────────────────────────────────────────────
    async def _infer(
        self,
        prompt: str,
        severity: Optional[Severity] = None,
        system_prompt: Optional[str] = None,
        expect_json: bool = False,
        is_trivial: bool = False,
        error_state: bool = False,
    ) -> tuple[str, ModelName]:
        """
        Wrapped inference call — passes agent identity for routing logs.
        Returns (response_text, model_used).
        """
        from services.llm_router import infer
        return await infer(
            prompt,
            severity=severity,
            system_prompt=system_prompt,
            expect_json=expect_json,
            is_trivial=is_trivial,
            error_state=error_state,
            agent=self.name,
        )

    # ── Shared error result builder ────────────────────────────────────────
    def _error_result(self, error: Exception) -> AgentResult:
        return AgentResult(
            agent=self.name,
            model_used=None,
            elapsed_ms=self._elapsed_ms(),
            success=False,
            error=str(error),
        )

    def __repr__(self) -> str:
        return f"<{self.name.value}>"