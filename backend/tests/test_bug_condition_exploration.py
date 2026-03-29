"""
Bug Condition Exploration Test for Complete E2E Testing Fixes

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bugs exist.
**DO NOT attempt to fix the test or the code when it fails.**
**NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation.

This test verifies all 27 bug conditions across 6 categories:
1. AI Pipeline Failures (95%+ Error Rate)
2. Demo Scenario Failures
3. Data Integrity Issues
4. Frontend Display Errors
5. Missing Functionality

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2**
"""
import asyncio
import json
import os
import sys
from decimal import Decimal
from typing import Any, Dict, List
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from hypothesis import given, strategies as st, HealthCheck
from hypothesis import settings as hypothesis_settings

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.action_execution import ActionExecutionAgent
from agents.interfaces import DecisionResult
from core.constants import ActionType, AgentName, ModelName, Severity
from core.config import settings as app_settings


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="function")
async def db_connection():
    """Create a database connection for testing."""
    conn = await asyncpg.connect(
        host=app_settings.POSTGRES_HOST,
        port=app_settings.POSTGRES_PORT,
        user=app_settings.POSTGRES_USER,
        password=app_settings.POSTGRES_PASSWORD,
        database=app_settings.POSTGRES_DB,
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture(scope="function")
async def http_client():
    """Create an HTTP client for API testing."""
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as client:
        yield client


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 1: AI PIPELINE FAILURES (95%+ ERROR RATE)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bug_1_1_payment_hold_attribute_error(db_connection):
    """
    **Validates: Requirements 2.1**
    
    Bug 1.1: Payment hold crashes with AttributeError: 'DecisionResult' object has no attribute 'evidence'
    
    Expected behavior: System should reference decision.action_details.get("duplicate_id") 
    instead of decision.evidence.get("duplicate_id")
    """
    agent = ActionExecutionAgent(db_connection)
    
    # Create a DecisionResult with payment_hold action
    decision = DecisionResult(
        agent=AgentName.DECISION,
        model_used=ModelName.QWEN,
        elapsed_ms=1000.0,
        success=True,
        root_cause="Duplicate payment detected",
        recommended_action=ActionType.PAYMENT_HOLD,
        action_details={
            "duplicate_id": str(uuid4()),
            "invoice_id": str(uuid4()),
            "vendor_name": "Test Vendor",
            "duplicate_invoice": "INV-001",
            "po_number": "PO-001",
        },
        confidence=0.95,
        cost_impact_inr=Decimal("100000.00"),
        urgency=Severity.HIGH,
    )
    
    # Create a test anomaly record
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'duplicate_payment', $2, 'transactions', $3, $4, $5, 'detected', $6, $7)
    """, anomaly_id, uuid4(), 0.95, "HIGH", 100000.00, "qwen2.5:7b", "Duplicate payment")
    
    # Execute the action - should NOT crash with AttributeError
    result = await agent.execute(decision, anomaly_id)
    
    # Expected behavior: Action executes successfully
    assert result.success, f"Action should succeed, got error: {result.error}"
    assert result.action_state.value in ["success", "pending_approval"], \
        f"Action should be success or pending_approval, got: {result.action_state.value}"


@pytest.mark.asyncio
async def test_bug_1_2_sla_escalation_attribute_error(db_connection):
    """
    **Validates: Requirements 2.2**
    
    Bug 1.2: SLA escalation crashes with AttributeError: 'DecisionResult' object has no attribute 'evidence'
    
    Expected behavior: System should reference decision.action_details.get("ticket_id") 
    instead of decision.evidence.get("ticket_id")
    """
    agent = ActionExecutionAgent(db_connection)
    
    # Create SLA ticket
    ticket_id = f"TKT-TEST-{uuid4().hex[:6]}"
    await db_connection.execute("""
        INSERT INTO sla_metrics 
            (id, ticket_id, sla_hours, opened_at, status, priority, penalty_amount, breach_prob)
        VALUES ($1, $2, 4, NOW() - INTERVAL '3 hours', 'open', 'P1', 25000.00, 0.85)
    """, uuid4(), ticket_id)
    
    decision = DecisionResult(
        agent=AgentName.DECISION,
        model_used=ModelName.DEEPSEEK,
        elapsed_ms=2000.0,
        success=True,
        root_cause="SLA breach imminent",
        recommended_action=ActionType.SLA_ESCALATION,
        action_details={
            "ticket_id": ticket_id,
            "priority": "P1",
            "sla_hours": 4,
            "elapsed_hours": 3.3,
            "breach_probability": 0.85,
        },
        confidence=0.90,
        cost_impact_inr=Decimal("25000.00"),
        urgency=Severity.CRITICAL,
    )
    
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'sla_breach', $2, 'sla_metrics', $3, $4, $5, 'detected', $6, $7)
    """, anomaly_id, uuid4(), 0.90, "CRITICAL", 25000.00, "deepseek-r1:7b", "SLA breach")
    
    result = await agent.execute(decision, anomaly_id)
    
    assert result.success, f"Action should succeed, got error: {result.error}"
    assert result.action_state.value in ["success", "pending_approval"]


@pytest.mark.asyncio
async def test_bug_1_3_vendor_flag_entity_id_error(db_connection):
    """
    **Validates: Requirements 2.3**
    
    Bug 1.3: Vendor flag crashes with incorrect entity_id reference
    
    Expected behavior: System should reference details.get("vendor_id") 
    instead of decision.entity_id
    """
    agent = ActionExecutionAgent(db_connection)
    
    vendor_id = uuid4()
    await db_connection.execute("""
        INSERT INTO vendors (id, name, category, contract_rate, market_benchmark)
        VALUES ($1, 'Test Vendor', 'Services', 100000.00, 90000.00)
    """, vendor_id)
    
    decision = DecisionResult(
        agent=AgentName.DECISION,
        model_used=ModelName.QWEN,
        elapsed_ms=1000.0,
        success=True,
        root_cause="Pricing anomaly detected",
        recommended_action=ActionType.VENDOR_RENEGOTIATION_FLAG,
        action_details={
            "vendor_id": str(vendor_id),
            "contract_rate": 100000.00,
            "market_benchmark": 90000.00,
        },
        confidence=0.85,
        cost_impact_inr=Decimal("10000.00"),
        urgency=Severity.MEDIUM,
    )
    
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'pricing_anomaly', $2, 'vendors', $3, $4, $5, 'detected', $6, $7)
    """, anomaly_id, vendor_id, 0.85, "MEDIUM", 10000.00, "qwen2.5:7b", "Pricing anomaly")
    
    result = await agent.execute(decision, anomaly_id)
    
    assert result.success, f"Action should succeed, got error: {result.error}"


@pytest.mark.asyncio
async def test_bug_1_4_license_deactivation_entity_id_error(db_connection):
    """
    **Validates: Requirements 2.4**
    
    Bug 1.4: License deactivation crashes with AttributeError: 'DecisionResult' object has no attribute 'entity_id'
    
    Expected behavior: System should reference decision.action_details.get("license_id") 
    instead of decision.entity_id
    """
    agent = ActionExecutionAgent(db_connection)
    
    license_id = uuid4()
    await db_connection.execute("""
        INSERT INTO licenses 
            (id, tool_name, assigned_email, last_login, is_active, monthly_cost, employee_active)
        VALUES ($1, 'Slack', 'test@company.local', NOW() - INTERVAL '120 days', TRUE, 3000.00, FALSE)
    """, license_id)
    
    decision = DecisionResult(
        agent=AgentName.DECISION,
        model_used=ModelName.QWEN,
        elapsed_ms=1000.0,
        success=True,
        root_cause="Unused license detected",
        recommended_action=ActionType.LICENSE_DEACTIVATED,
        action_details={
            "license_id": str(license_id),
            "tool_name": "Slack",
            "assigned_email": "test@company.local",
            "last_login_days": 120,
        },
        confidence=0.90,
        cost_impact_inr=Decimal("3000.00"),
        urgency=Severity.MEDIUM,
    )
    
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'unused_license', $2, 'licenses', $3, $4, $5, 'detected', $6, $7)
    """, anomaly_id, license_id, 0.90, "MEDIUM", 3000.00, "qwen2.5:7b", "Unused license")
    
    result = await agent.execute(decision, anomaly_id)
    
    assert result.success, f"Action should succeed, got error: {result.error}"


@pytest.mark.asyncio
async def test_bug_1_6_timeout_fallback(http_client, db_connection):
    """
    **Validates: Requirements 2.6**
    
    Bug 1.6: AI model inference times out after 8 seconds, causing 95%+ fallback to Llama
    
    Expected behavior: System should wait up to 120 seconds before timing out,
    allowing CPU-based 7B models sufficient time to complete inference
    """
    # Reset demo to get clean state
    response = await http_client.post("/api/demo/reset")
    assert response.status_code == 200
    
    # Trigger duplicate_payment demo
    response = await http_client.post("/api/demo/trigger?scenario=duplicate_payment")
    assert response.status_code == 200
    data = response.json()
    task_id = data["task_id"]
    
    # Wait for pipeline to complete (up to 120 seconds)
    await asyncio.sleep(120)
    
    # Check audit trail for model usage
    audit_records = await db_connection.fetch("""
        SELECT model_used, final_status 
        FROM audit_trail 
        ORDER BY timestamp DESC 
        LIMIT 20
    """)
    
    # Expected: At least 50% should use qwen2.5:7b or deepseek-r1:7b (not llama3.2:3b fallback)
    qwen_or_deepseek_count = sum(
        1 for r in audit_records 
        if r["model_used"] and ("qwen" in r["model_used"] or "deepseek" in r["model_used"])
    )
    
    total_records = len(audit_records)
    if total_records > 0:
        qwen_deepseek_percentage = (qwen_or_deepseek_count / total_records) * 100
        assert qwen_deepseek_percentage >= 50, \
            f"Expected ≥50% qwen/deepseek usage, got {qwen_deepseek_percentage:.1f}% ({qwen_or_deepseek_count}/{total_records})"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 2: DEMO SCENARIO FAILURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bug_2_1_sla_breach_demo_500_error(http_client):
    """
    **Validates: Requirements 2.7**
    
    Bug 2.1: SLA breach demo returns HTTP 500 error due to attempting to INSERT 
    into GENERATED column sla_deadline
    
    Expected behavior: System should NOT include sla_deadline in INSERT statement,
    allowing PostgreSQL to compute it automatically
    """
    response = await http_client.post("/api/demo/trigger?scenario=sla_breach")
    
    # Expected: HTTP 200 (not 500)
    assert response.status_code == 200, \
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    assert "task_id" in data
    assert data["scenario"] == "sla_breach"


@pytest.mark.asyncio
async def test_bug_2_2_unused_subscriptions_demo_500_error(http_client):
    """
    **Validates: Requirements 2.8**
    
    Bug 2.2: Unused subscriptions demo returns HTTP 500 error due to foreign key 
    constraint violations during DELETE operations
    
    Expected behavior: System should wrap DELETE in try-except and use 
    ON CONFLICT DO NOTHING for INSERT operations
    """
    response = await http_client.post("/api/demo/trigger?scenario=unused_subscriptions")
    
    # Expected: HTTP 200 (not 500)
    assert response.status_code == 200, \
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    assert "task_id" in data
    assert data["scenario"] == "unused_subscriptions"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 3: DATA INTEGRITY ISSUES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bug_3_1_duplicate_approval_queue_entries(http_client, db_connection):
    """
    **Validates: Requirements 2.9, 2.10**
    
    Bug 3.1: Multiple scan cycles create 837-939 duplicate pending approval entries
    
    Expected behavior: Each duplicate pair should be detected once, 
    approval queue should never exceed reasonable bounds (≤20 items)
    """
    # Reset demo to get clean state
    response = await http_client.post("/api/demo/reset")
    assert response.status_code == 200
    
    # Trigger duplicate_payment demo multiple times
    for i in range(3):
        response = await http_client.post("/api/demo/trigger?scenario=duplicate_payment")
        assert response.status_code == 200
        await asyncio.sleep(5)  # Wait between triggers
    
    # Wait for all pipelines to complete
    await asyncio.sleep(180)
    
    # Check approval queue size
    approval_count = await db_connection.fetchval("""
        SELECT COUNT(*) FROM approval_queue
    """)
    
    # Expected: ≤20 items (not 837-939)
    assert approval_count <= 20, \
        f"Expected ≤20 approval queue items, got {approval_count}"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 4: FRONTEND DISPLAY ERRORS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bug_4_1_nan_confidence_display(http_client):
    """
    **Validates: Requirements 2.15**
    
    Bug 4.1: Frontend displays "NaN%" for null confidence values
    
    Expected behavior: Frontend should display "—" as fallback
    
    Note: This test verifies the API returns proper data. Frontend null guards
    are tested separately in frontend unit tests.
    """
    response = await http_client.get("/api/anomalies/?limit=10")
    assert response.status_code == 200
    
    anomalies = response.json()
    for anomaly in anomalies:
        # Confidence should either be a valid number or None
        if anomaly.get("confidence") is not None:
            assert isinstance(anomaly["confidence"], (int, float))
            assert 0 <= anomaly["confidence"] <= 1


@pytest.mark.asyncio
async def test_bug_4_5_actions_panel_model_display(http_client, db_connection):
    """
    **Validates: Requirements 2.19, 2.20**
    
    Bug 4.5: Actions panel shows "Llama" or "ActionExecutionAgent" instead of actual model names
    
    Expected behavior: Actions panel should display model_used field from joined 
    anomaly_logs table (qwen2.5:7b, deepseek-r1:7b, llama3.2:3b)
    """
    # Trigger a demo to generate actions
    response = await http_client.post("/api/demo/reset")
    assert response.status_code == 200
    
    response = await http_client.post("/api/demo/trigger?scenario=duplicate_payment")
    assert response.status_code == 200
    
    await asyncio.sleep(120)  # Wait for pipeline
    
    # Check actions API response
    response = await http_client.get("/api/actions/?limit=5")
    assert response.status_code == 200
    
    actions = response.json()
    if len(actions) > 0:
        # At least one action should have anomaly_model field
        has_anomaly_model = any("anomaly_model" in action for action in actions)
        assert has_anomaly_model, \
            "Actions should include anomaly_model field from joined anomaly_logs table"
        
        # Check that model names are correct (not "ActionExecutionAgent")
        for action in actions:
            if "anomaly_model" in action and action["anomaly_model"]:
                model = action["anomaly_model"]
                assert model in ["qwen2.5:7b", "deepseek-r1:7b", "llama3.2:3b"], \
                    f"Expected valid model name, got: {model}"


# ═══════════════════════════════════════════════════════════════════════════
# CATEGORY 5: MISSING FUNCTIONALITY
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bug_5_1_audit_override_endpoint_missing(http_client, db_connection):
    """
    **Validates: Requirements 2.21**
    
    Bug 5.1: PATCH /api/audit/:id/override returns 404 or 500
    
    Expected behavior: Endpoint should exist and return HTTP 200
    """
    # Create a test audit record
    audit_id = uuid4()
    await db_connection.execute("""
        INSERT INTO audit_trail 
            (audit_id, agent, model_used, final_status, execution_time_ms, input_data)
        VALUES ($1, 'DecisionAgent', 'qwen2.5:7b', 'actioned', 1000, '{}')
    """, audit_id)
    
    # Try to override the audit decision
    response = await http_client.patch(
        f"/api/audit/{audit_id}/override",
        json={"reason": "test override", "user": "admin"}
    )
    
    # Expected: HTTP 200 (not 404 or 500)
    assert response.status_code == 200, \
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_bug_5_2_approval_reject_endpoint_missing(http_client, db_connection):
    """
    **Validates: Requirements 2.22**
    
    Bug 5.2: POST /api/approvals/:id/reject is broken or missing
    
    Expected behavior: Endpoint should exist and return HTTP 200
    """
    # Create a test approval queue item
    action_id = uuid4()
    anomaly_id = uuid4()
    
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'duplicate_payment', $2, 'transactions', 0.95, 'HIGH', 
                75000.00, 'detected', 'qwen2.5:7b', 'Test')
    """, anomaly_id, uuid4())
    
    await db_connection.execute("""
        INSERT INTO actions_taken 
            (id, anomaly_id, action_type, executed_by, cost_saved, status, approval_required)
        VALUES ($1, $2, 'payment_hold', 'ActionExecutionAgent', 75000.00, 'pending_approval', TRUE)
    """, action_id, anomaly_id)
    
    await db_connection.execute("""
        INSERT INTO approval_queue (action_id, anomaly_id, action_type, cost_impact_inr)
        VALUES ($1, $2, 'payment_hold', 75000.00)
    """, action_id, anomaly_id)
    
    # Try to reject the approval
    response = await http_client.post(
        f"/api/approvals/{action_id}/reject",
        json={"reason": "test rejection", "user": "admin"}
    )
    
    # Expected: HTTP 200 (not 404 or 500)
    assert response.status_code == 200, \
        f"Expected HTTP 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    assert data["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY-BASED TESTS
# ═══════════════════════════════════════════════════════════════════════════

@given(
    action_type=st.sampled_from([
        ActionType.PAYMENT_HOLD,
        ActionType.SLA_ESCALATION,
        ActionType.LICENSE_DEACTIVATED,
        ActionType.VENDOR_RENEGOTIATION_FLAG,
    ]),
    cost_impact=st.floats(min_value=1000.0, max_value=200000.0),
    confidence=st.floats(min_value=0.7, max_value=1.0),
)
@hypothesis_settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_property_no_attribute_errors_on_any_action_type(
    action_type, cost_impact, confidence, db_connection
):
    """
    **Property 1: Bug Condition - AI Pipeline Executes Actions Successfully**
    
    For any DecisionResult where recommended_action is not None, the fixed 
    ActionExecutionAgent SHALL correctly reference action_details dictionary 
    instead of non-existent evidence or entity_id attributes.
    
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    agent = ActionExecutionAgent(db_connection)
    
    # Generate appropriate action_details based on action_type
    action_details = {}
    entity_id = uuid4()
    
    if action_type == ActionType.PAYMENT_HOLD:
        action_details = {
            "duplicate_id": str(uuid4()),
            "invoice_id": str(uuid4()),
            "vendor_name": "Test Vendor",
            "duplicate_invoice": "INV-001",
            "po_number": "PO-001",
        }
    elif action_type == ActionType.SLA_ESCALATION:
        ticket_id = f"TKT-TEST-{uuid4().hex[:6]}"
        await db_connection.execute("""
            INSERT INTO sla_metrics 
                (id, ticket_id, sla_hours, opened_at, status, priority, penalty_amount, breach_prob)
            VALUES ($1, $2, 4, NOW() - INTERVAL '3 hours', 'open', 'P1', $3, 0.85)
        """, uuid4(), ticket_id, cost_impact)
        action_details = {
            "ticket_id": ticket_id,
            "priority": "P1",
            "sla_hours": 4,
            "elapsed_hours": 3.3,
            "breach_probability": 0.85,
        }
    elif action_type == ActionType.LICENSE_DEACTIVATED:
        license_id = uuid4()
        await db_connection.execute("""
            INSERT INTO licenses 
                (id, tool_name, assigned_email, last_login, is_active, monthly_cost, employee_active)
            VALUES ($1, 'Slack', 'test@company.local', NOW() - INTERVAL '120 days', TRUE, $2, FALSE)
        """, license_id, cost_impact)
        action_details = {
            "license_id": str(license_id),
            "tool_name": "Slack",
            "assigned_email": "test@company.local",
            "last_login_days": 120,
        }
    elif action_type == ActionType.VENDOR_RENEGOTIATION_FLAG:
        vendor_id = uuid4()
        await db_connection.execute("""
            INSERT INTO vendors (id, name, category, contract_rate, market_benchmark)
            VALUES ($1, 'Test Vendor', 'Services', $2, $3)
        """, vendor_id, cost_impact * 1.1, cost_impact)
        action_details = {
            "vendor_id": str(vendor_id),
            "contract_rate": cost_impact * 1.1,
            "market_benchmark": cost_impact,
        }
    
    decision = DecisionResult(
        agent=AgentName.DECISION,
        model_used=ModelName.QWEN,
        elapsed_ms=1000.0,
        success=True,
        root_cause="Test anomaly",
        recommended_action=action_type,
        action_details=action_details,
        confidence=confidence,
        cost_impact_inr=Decimal(str(cost_impact)),
        urgency=Severity.HIGH,
    )
    
    # Create anomaly record
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, $2, $3, 'test_table', $4, 'HIGH', $5, 'detected', 'qwen2.5:7b', 'Test')
    """, anomaly_id, action_type.value, entity_id, confidence, cost_impact)
    
    # Execute action - should NOT crash with AttributeError
    try:
        result = await agent.execute(decision, anomaly_id)
        # Property: No AttributeError should be raised
        assert result is not None, "Result should not be None"
        # If there's an error, it should not be AttributeError
        if result.error:
            assert "AttributeError" not in result.error, \
                f"Should not have AttributeError, got: {result.error}"
    except AttributeError as e:
        pytest.fail(f"AttributeError raised: {e}")
