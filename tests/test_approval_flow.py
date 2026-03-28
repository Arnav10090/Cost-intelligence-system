"""
Tests for the approval workflow and override flow.

Covers:
  - requires_approval() threshold gate
  - Full lifecycle: PENDING_APPROVAL → APPROVED → SUCCESS
  - Full lifecycle: PENDING_APPROVAL → REJECTED
  - Override: SUCCESS → OVERRIDDEN + rollback dispatched
  - Edge cases: double-approve, wrong state transitions
"""
import uuid
import json
import pytest
import pytest_asyncio
from decimal import Decimal
from datetime import datetime, timezone

from core.constants import ActionState
from services.approval_service import requires_approval


# ═══════════════════════════════════════════════════════════════════════════
# requires_approval() gate
# ═══════════════════════════════════════════════════════════════════════════
class TestRequiresApprovalGate:
    def test_below_threshold_no_approval_needed(self):
        """₹49,999 — below ₹50,000 limit — auto-approve."""
        assert requires_approval(49_999) is False

    def test_exactly_at_threshold_no_approval_needed(self):
        """₹50,000 exactly — auto-approve (> not >=)."""
        assert requires_approval(50_000) is False

    def test_above_threshold_needs_approval(self):
        """₹50,001 — requires human approval."""
        assert requires_approval(50_001) is True

    def test_high_value_always_needs_approval(self):
        """Large payments always need approval."""
        assert requires_approval(1_00_000) is True
        assert requires_approval(10_00_000) is True

    def test_zero_no_approval_needed(self):
        assert requires_approval(0) is False

    def test_negative_no_approval_needed(self):
        """Negative amounts (credit notes) don't need approval."""
        assert requires_approval(-1000) is False


# ═══════════════════════════════════════════════════════════════════════════
# Helpers — insert test anomaly and action
# ═══════════════════════════════════════════════════════════════════════════
async def _insert_anomaly(db, cost_impact=45000.0):
    anomaly_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO anomaly_logs
            (id, anomaly_type, confidence, severity, cost_impact_inr, status, model_used)
        VALUES ($1, 'duplicate_payment', 0.97, 'HIGH', $2, 'detected', 'qwen2.5:7b')
    """, anomaly_id, cost_impact)
    return anomaly_id


async def _insert_action(db, anomaly_id, status="pending_approval", cost_saved=45000.0):
    action_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO actions_taken
            (id, anomaly_id, action_type, executed_by, cost_saved,
             status, approval_required, payload, rollback_payload)
        VALUES ($1, $2, 'payment_hold', 'ActionExecutionAgent', $3,
                $4, TRUE,
                $5::jsonb, $6::jsonb)
    """,
        action_id, anomaly_id, cost_saved, status,
        json.dumps({"invoice_id": str(uuid.uuid4()), "amount": cost_saved}),
        json.dumps({"invoice_id": str(uuid.uuid4())}),
    )
    return action_id


# ═══════════════════════════════════════════════════════════════════════════
# Approval lifecycle
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestApproveAction:
    async def test_approve_transitions_to_success(self, db, seed_db):
        from services.approval_service import approve_action
        from unittest.mock import AsyncMock, patch

        anomaly_id = await _insert_anomaly(db, 45000.0)
        action_id = await _insert_action(db, anomaly_id)

        # Mock out the execution dispatch (we test that separately)
        with patch(
            "services.approval_service._execute_approved_action",
            new_callable=AsyncMock,
        ):
            result = await approve_action(db, action_id, approved_by="finance_manager")

        assert result["status"] in (
            ActionState.APPROVED.value, ActionState.SUCCESS.value
        )
        assert result["approved_by"] == "finance_manager"
        assert result["approval_timestamp"] is not None

    async def test_approve_wrong_state_raises(self, db, seed_db):
        """Cannot approve an action that is already in SUCCESS state."""
        from services.approval_service import approve_action

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id, status="success")

        with pytest.raises(ValueError, match="not in PENDING_APPROVAL"):
            await approve_action(db, action_id, approved_by="finance_manager")

    async def test_approve_nonexistent_action_raises(self, db, seed_db):
        from services.approval_service import approve_action

        with pytest.raises(ValueError):
            await approve_action(db, uuid.uuid4(), approved_by="anyone")


# ═══════════════════════════════════════════════════════════════════════════
# Rejection lifecycle
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestRejectAction:
    async def test_reject_transitions_to_rejected(self, db, seed_db):
        from services.approval_service import reject_action

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id)

        result = await reject_action(
            db, action_id,
            rejected_by="cfo",
            reason="Vendor dispute under review — do not hold",
        )

        assert result["status"] == ActionState.REJECTED.value
        assert result["rejection_reason"] == "Vendor dispute under review — do not hold"

    async def test_reject_records_reviewer(self, db, seed_db):
        from services.approval_service import reject_action

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id)

        result = await reject_action(db, action_id, rejected_by="cfo", reason="reason")
        assert result["approved_by"] == "cfo"

    async def test_reject_wrong_state_raises(self, db, seed_db):
        from services.approval_service import reject_action

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id, status="rejected")  # already rejected

        with pytest.raises(ValueError):
            await reject_action(db, action_id, rejected_by="cfo", reason="x")


# ═══════════════════════════════════════════════════════════════════════════
# Override / rollback lifecycle  (blueprint §11A)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestOverrideAction:
    async def test_override_transitions_to_overridden(self, db, seed_db):
        from services.approval_service import override_action
        from unittest.mock import AsyncMock, patch

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id, status="success")

        with patch(
            "services.approval_service._execute_rollback",
            new_callable=AsyncMock,
        ), patch(
            "services.approval_service._write_override_audit",
            new_callable=AsyncMock,
        ):
            result = await override_action(
                db, action_id,
                overridden_by="finance_analyst",
                reason="False positive duplicate detection",
            )

        assert result["status"] == ActionState.OVERRIDDEN.value
        assert result["rolled_back_at"] is not None

    async def test_override_updates_anomaly_status(self, db, seed_db):
        from services.approval_service import override_action
        from unittest.mock import AsyncMock, patch

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id, status="success")

        with patch(
            "services.approval_service._execute_rollback", new_callable=AsyncMock
        ), patch(
            "services.approval_service._write_override_audit", new_callable=AsyncMock
        ):
            await override_action(db, action_id, "analyst", "False positive")

        anomaly = await db.fetchrow(
            "SELECT status, override_reason FROM anomaly_logs WHERE id = $1",
            anomaly_id,
        )
        assert anomaly["status"] == "overridden"
        assert anomaly["override_reason"] == "False positive"

    async def test_override_non_success_action_raises(self, db, seed_db):
        """Cannot override an action that hasn't been executed yet."""
        from services.approval_service import override_action

        anomaly_id = await _insert_anomaly(db)
        action_id = await _insert_action(db, anomaly_id, status="pending_approval")

        with pytest.raises(ValueError, match="not in SUCCESS state"):
            await override_action(db, action_id, "analyst", "reason")


# ═══════════════════════════════════════════════════════════════════════════
# ActionState enum helpers
# ═══════════════════════════════════════════════════════════════════════════
class TestActionStateEnum:
    def test_terminal_states(self):
        assert ActionState.SUCCESS.is_terminal is True
        assert ActionState.FAILED.is_terminal is True
        assert ActionState.REJECTED.is_terminal is True
        assert ActionState.ROLLED_BACK.is_terminal is True
        assert ActionState.OVERRIDDEN.is_terminal is True

    def test_non_terminal_states(self):
        assert ActionState.PENDING.is_terminal is False
        assert ActionState.PENDING_APPROVAL.is_terminal is False
        assert ActionState.APPROVED.is_terminal is False

    def test_reversible_states(self):
        assert ActionState.SUCCESS.is_reversible is True
        assert ActionState.APPROVED.is_reversible is True

    def test_non_reversible_states(self):
        assert ActionState.REJECTED.is_reversible is False
        assert ActionState.OVERRIDDEN.is_reversible is False
        assert ActionState.PENDING_APPROVAL.is_reversible is False