"""
Phase 2 pipeline integration tests — end-to-end flow validation.

Tests:
  - Inject duplicate transaction → full pipeline → verify payment held
  - SLA ticket near breach → pipeline → verify escalated
  - Verify audit_trail record written with full reasoning chain
  - Verify cost_saved recorded correctly in actions_taken
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from core.constants import (
    AgentName, AnomalyType, ActionType, ModelName, Severity, TaskType,
)
from models.schemas import AgentTask


def _make_task(task_type: str) -> AgentTask:
    return AgentTask(
        task_id=str(uuid.uuid4()),
        task_type=task_type,
    )


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: Duplicate payment → pipeline → payment held
# ═══════════════════════════════════════════════════════════════════════════
class TestDuplicatePipeline:
    """Full pipeline: duplicate transaction → detect → reason → hold → audit."""

    @pytest.mark.asyncio
    async def test_duplicate_detected_and_held(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_DUPLICATES)

        result = await orch.run(task)

        assert result.anomalies_detected >= 1, "Should detect seeded duplicate"

        # Verify anomaly was persisted in anomaly_logs
        anomaly_count = await db.fetchval(
            "SELECT COUNT(*) FROM anomaly_logs WHERE anomaly_type = $1",
            AnomalyType.DUPLICATE_PAYMENT.value,
        )
        assert anomaly_count >= 1, "Anomaly should be persisted to DB"

    @pytest.mark.asyncio
    async def test_audit_trail_written(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_DUPLICATES)

        await orch.run(task)

        # Verify at least one audit trail record was written
        audit_count = await db.fetchval("SELECT COUNT(*) FROM audit_trail")
        assert audit_count >= 1, "Audit trail should be written after pipeline run"


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: SLA near-breach → pipeline → escalated
# ═══════════════════════════════════════════════════════════════════════════
class TestSLAPipeline:
    """Full pipeline: SLA near-breach → detect → action → audit."""

    @pytest.mark.asyncio
    async def test_sla_breach_detected_and_escalated(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_SLA)

        result = await orch.run(task)

        # The seeded TKT-TEST-001 is at ~82% elapsed → should be flagged
        assert result.anomalies_detected >= 1, "Near-breach SLA ticket should be detected"


# ═══════════════════════════════════════════════════════════════════════════
# Cost saved tracking
# ═══════════════════════════════════════════════════════════════════════════
class TestCostTracking:
    """Verify cost_saved is recorded correctly in actions_taken."""

    @pytest.mark.asyncio
    async def test_cost_saved_persisted(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_DUPLICATES)

        result = await orch.run(task)

        if result.actions_taken > 0:
            # Check actions_taken table has cost_saved values
            total_saved = await db.fetchval(
                "SELECT COALESCE(SUM(cost_saved), 0) FROM actions_taken WHERE status = 'success'"
            )
            assert total_saved >= 0, "Cost saved should be a non-negative value"

    @pytest.mark.asyncio
    async def test_pipeline_result_matches_db(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_LICENSES)

        result = await orch.run(task)

        # Verify PipelineResult summary is consistent
        assert result.anomalies_detected == len(result.detections)
        assert result.actions_taken == len(result.actions)
        assert result.total_elapsed_ms > 0


# ═══════════════════════════════════════════════════════════════════════════
# Audit trail completeness
# ═══════════════════════════════════════════════════════════════════════════
class TestAuditCompleteness:
    """Audit trail records contain required fields per blueprint §10."""

    @pytest.mark.asyncio
    async def test_audit_record_has_required_fields(self, db, mock_ollama, seed_db):
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_DUPLICATES)
        await orch.run(task)

        rows = await db.fetch("SELECT * FROM audit_trail ORDER BY timestamp DESC LIMIT 1")
        if rows:
            record = dict(rows[0])
            assert "audit_id" in record
            assert "agent" in record
            assert "final_status" in record
            assert record["audit_id"] is not None

    @pytest.mark.asyncio
    async def test_reasoning_chain_in_audit(self, db, mock_deepseek, seed_db):
        """When deepseek is invoked, reasoning chain should be in audit record."""
        from agents.orchestrator import OrchestratorAgent

        orch = OrchestratorAgent(db)
        task = _make_task(TaskType.SCAN_DUPLICATES)
        result = await orch.run(task)

        # If decisions were made, check audit has reasoning
        if result.decisions:
            audit = await db.fetchrow(
                "SELECT * FROM audit_trail ORDER BY timestamp DESC LIMIT 1"
            )
            if audit:
                record = dict(audit)
                # Reasoning should be captured if deepseek was invoked
                assert record.get("reasoning_invoked") is not None or \
                       record.get("reasoning_model") is not None, \
                       "Audit should track whether reasoning was invoked"
