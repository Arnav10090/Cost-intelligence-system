"""
Phase 2 agent tests — roadmap §Phase 2 Tests.

Tests:
  - OrchestratorAgent routes to correct sub-agent based on task_type
  - AnomalyDetectionAgent.scan_duplicates() finds seeded duplicate pairs
  - AnomalyDetectionAgent.scan_sla() flags near-breach tickets
  - AnomalyDetectionAgent.scan_licenses() flags terminated + inactive licenses
  - DecisionAgent parses deepseek JSON output correctly
  - FallbackAgent handles exceptions without propagating
"""
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from core.constants import (
    AgentName, AnomalyType, ActionType, ModelName, Severity, TaskType,
)
from agents.interfaces import (
    AgentResult, DetectionResult, DecisionResult, ActionResult, PipelineResult,
)
from models.schemas import AgentTask


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
def _make_task(task_type: str = TaskType.SCAN_DUPLICATES) -> AgentTask:
    return AgentTask(
        task_id=str(uuid.uuid4()),
        task_type=task_type,
    )


# ═══════════════════════════════════════════════════════════════════════════
# OrchestratorAgent — routing by task_type
# ═══════════════════════════════════════════════════════════════════════════
class TestOrchestratorRouting:
    """Orchestrator dispatches to the correct sub-agent based on task_type."""

    @pytest.mark.asyncio
    async def test_routes_scan_duplicates(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent(db)

        task = _make_task(TaskType.SCAN_DUPLICATES)
        result = await orch.run(task)

        assert isinstance(result, PipelineResult)
        assert result.task_type == TaskType.SCAN_DUPLICATES

    @pytest.mark.asyncio
    async def test_routes_scan_sla(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent(db)

        task = _make_task(TaskType.SCAN_SLA)
        result = await orch.run(task)

        assert isinstance(result, PipelineResult)
        assert result.task_type == TaskType.SCAN_SLA

    @pytest.mark.asyncio
    async def test_routes_scan_licenses(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent(db)

        task = _make_task(TaskType.SCAN_LICENSES)
        result = await orch.run(task)

        assert isinstance(result, PipelineResult)
        assert result.task_type == TaskType.SCAN_LICENSES

    @pytest.mark.asyncio
    async def test_empty_scan_returns_zero_detections(self, db, mock_ollama):
        """When no seed data, scans should return 0 detections gracefully."""
        from agents.orchestrator import OrchestratorAgent
        orch = OrchestratorAgent(db)

        task = _make_task(TaskType.SCAN_DUPLICATES)
        result = await orch.run(task)

        assert result.anomalies_detected == 0
        assert result.errors == []


# ═══════════════════════════════════════════════════════════════════════════
# AnomalyDetectionAgent — scan_duplicates
# ═══════════════════════════════════════════════════════════════════════════
class TestDuplicateDetection:
    """Validate the duplicate payment detection with seeded data."""

    @pytest.mark.asyncio
    async def test_finds_seeded_duplicate_pair(self, db, seed_db):
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_duplicates()

        assert len(results) >= 1, "Should find at least the seeded duplicate pair"
        for r in results:
            assert r.anomaly_type == AnomalyType.DUPLICATE_PAYMENT
            assert r.confidence > 0.0

    @pytest.mark.asyncio
    async def test_duplicate_confidence_same_po(self, db, seed_db):
        """Same PO → confidence should be 0.97 tier."""
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_duplicates()
        # The seeded pair has the same PO (PO-TEST-001)
        high_conf = [r for r in results if r.confidence >= 0.90]
        assert len(high_conf) >= 1, "Same-PO pair should have confidence >= 0.90"


# ═══════════════════════════════════════════════════════════════════════════
# AnomalyDetectionAgent — scan_sla
# ═══════════════════════════════════════════════════════════════════════════
class TestSLADetection:
    """Validate SLA breach detection with seeded near-breach ticket."""

    @pytest.mark.asyncio
    async def test_flags_near_breach_ticket(self, db, seed_db):
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_sla()

        # TKT-TEST-001 is P1, 4h SLA, opened 3.3h ago = ~82% elapsed
        flagged_ids = [str(r.evidence.get("ticket_id", "")) for r in results]
        assert any("TKT-TEST-001" in tid for tid in flagged_ids), \
            "Near-breach ticket TKT-TEST-001 should be flagged"

    @pytest.mark.asyncio
    async def test_safe_ticket_not_flagged(self, db, seed_db):
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_sla()

        # TKT-TEST-002 is P3, 24h SLA, only 4h elapsed = ~17% → should NOT be flagged
        flagged_ids = [str(r.evidence.get("ticket_id", "")) for r in results]
        assert not any("TKT-TEST-002" in tid for tid in flagged_ids), \
            "Safe ticket TKT-TEST-002 should not be flagged"


# ═══════════════════════════════════════════════════════════════════════════
# AnomalyDetectionAgent — scan_licenses
# ═══════════════════════════════════════════════════════════════════════════
class TestLicenseDetection:
    """Validate unused license detection."""

    @pytest.mark.asyncio
    async def test_flags_terminated_employee_license(self, db, seed_db):
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_licenses()

        terminated = [r for r in results if r.confidence >= 0.95]
        assert len(terminated) >= 1, "Terminated employee license should be flagged with high confidence"

    @pytest.mark.asyncio
    async def test_flags_inactive_license(self, db, seed_db):
        from agents.anomaly_detection import AnomalyDetectionAgent
        agent = AnomalyDetectionAgent(db)

        results = await agent.scan_licenses()

        # Should find at least the 65-day inactive license too
        assert len(results) >= 2, "Both terminated and inactive licenses should be flagged"


# ═══════════════════════════════════════════════════════════════════════════
# DecisionAgent — JSON parsing
# ═══════════════════════════════════════════════════════════════════════════
class TestDecisionAgent:
    """DecisionAgent correctly parses deepseek JSON response."""

    @pytest.mark.asyncio
    async def test_parses_valid_json(self, db, mock_deepseek):
        from agents.decision_agent import DecisionAgent

        agent = DecisionAgent(db)

        # Build a minimal detection for the agent to reason about
        detection = DetectionResult(
            agent=AgentName.ANOMALY,
            model_used=None,
            elapsed_ms=10.0,
            success=True,
            anomaly_type=AnomalyType.DUPLICATE_PAYMENT,
            entity_id=uuid.uuid4(),
            entity_table="transactions",
            confidence=0.82,
            severity=Severity.HIGH,
            cost_impact_inr=Decimal("45000"),
            evidence={"po_number": "PO-2891"},
        )

        result = await agent.reason(detection, extra_context={})

        assert isinstance(result, DecisionResult)
        assert result.success is True
        assert result.root_cause != ""
        assert result.model_used == ModelName.DEEPSEEK

    @pytest.mark.asyncio
    async def test_handles_malformed_json_gracefully(self, db):
        """When deepseek returns garbage, DecisionAgent should not crash."""
        from agents.decision_agent import DecisionAgent
        from core.constants import ModelName

        with patch("services.llm_router.infer", new_callable=AsyncMock) as mock:
            mock.return_value = ("not valid json at all {{{", ModelName.DEEPSEEK)

            agent = DecisionAgent(db)
            detection = DetectionResult(
                agent=AgentName.ANOMALY,
                model_used=None,
                elapsed_ms=10.0,
                success=True,
                anomaly_type=AnomalyType.DUPLICATE_PAYMENT,
                entity_id=uuid.uuid4(),
                entity_table="transactions",
                confidence=0.85,
                severity=Severity.HIGH,
                cost_impact_inr=Decimal("50000"),
            )

            result = await agent.reason(detection, extra_context={})
            # Should return a result (possibly degraded) without raising
            assert isinstance(result, DecisionResult)


# ═══════════════════════════════════════════════════════════════════════════
# FallbackAgent — error handling
# ═══════════════════════════════════════════════════════════════════════════
class TestFallbackAgent:
    """FallbackAgent handles exceptions without propagating."""

    @pytest.mark.asyncio
    async def test_handle_error_returns_agent_result(self, db, mock_ollama):
        from agents.fallback_agent import FallbackAgent

        agent = FallbackAgent(db)
        task = _make_task()

        error = RuntimeError("Simulated agent failure")
        result = await agent.handle_error(error, task)

        assert isinstance(result, AgentResult)
        assert result.success is False
        assert result.agent == AgentName.FALLBACK
        assert result.model_used == ModelName.LLAMA

    @pytest.mark.asyncio
    async def test_does_not_propagate_exception(self, db, mock_ollama):
        from agents.fallback_agent import FallbackAgent

        agent = FallbackAgent(db)
        task = _make_task()

        # Even with a critical error, handle_error should NOT raise
        error = Exception("Critical database failure")
        try:
            result = await agent.handle_error(error, task)
        except Exception:
            pytest.fail("FallbackAgent must NEVER propagate exceptions")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_delegates_to_handle_error(self, db, mock_ollama):
        from agents.fallback_agent import FallbackAgent

        agent = FallbackAgent(db)
        task = _make_task()

        result = await agent.run(task)

        assert isinstance(result, AgentResult)
        assert result.success is False
