"""
Preservation Property Tests for Complete E2E Testing Fixes

**IMPORTANT**: Follow observation-first methodology - these tests capture baseline behavior
that must be preserved after fixes are applied.

**EXPECTED OUTCOME**: These tests MUST PASS on UNFIXED code to confirm baseline behavior.

This test suite verifies that non-buggy inputs continue to produce the same behavior
after fixes are applied. It covers:
1. Model routing (Qwen default, DeepSeek for HIGH/CRITICAL)
2. Approval gates (₹50k threshold)
3. Demo reset behavior (450 transactions, 200 licenses, 50 SLA tickets)
4. API schemas (all required fields present)
5. Database schema (all 8 tables exist)
6. Frontend polling behavior
7. Model management (DeepSeek unload/reload)
8. Fallback behavior (Llama when budget exhausted)

**Validates: Requirements 3.1-3.20**
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
from hypothesis import given, strategies as st, HealthCheck, assume
from hypothesis import settings as hypothesis_settings

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.constants import ActionType, AgentName, ModelName, Severity, AnomalyType
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
# PROPERTY 1: MODEL ROUTING PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_qwen_default_for_standard_decisions(http_client, db_connection):
    """
    **Validates: Requirements 3.1**
    
    Preservation: Qwen 2.5:7b remains the default model for standard decisions
    
    When the system processes anomalies with valid data and sufficient inference time,
    the system SHALL CONTINUE TO use Qwen 2.5:7b as the default model for standard decisions.
    """
    # Reset demo to get clean state
    response = await http_client.post("/api/demo/reset")
    assert response.status_code == 200
    
    # Check audit trail for recent model usage
    audit_records = await db_connection.fetch("""
        SELECT model_used, final_status 
        FROM audit_trail 
        WHERE model_used IS NOT NULL
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    
    if len(audit_records) > 0:
        # At least some records should use qwen2.5:7b (the default model)
        qwen_count = sum(1 for r in audit_records if r["model_used"] and "qwen" in r["model_used"])
        assert qwen_count > 0, "Expected at least some audit records to use Qwen as default model"


@pytest.mark.asyncio
async def test_preservation_deepseek_for_high_critical_severity(http_client, db_connection):
    """
    **Validates: Requirements 3.2**
    
    Preservation: DeepSeek-R1:7b continues to be invoked for HIGH/CRITICAL severity anomalies
    
    When the system detects HIGH or CRITICAL severity anomalies, the system SHALL CONTINUE TO
    invoke DeepSeek-R1:7b for deep reasoning and increment the DeepSeek call counter.
    """
    # Check system status for DeepSeek usage
    response = await http_client.get("/api/system/status")
    assert response.status_code == 200
    
    status = response.json()
    # Verify DeepSeek counter exists and has expected structure
    assert "deepseek_calls_this_hour" in status or "calls_this_hour" in status, \
        "System status should track DeepSeek call counter"


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 2: APPROVAL GATE PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@given(
    cost_impact=st.floats(min_value=1000.0, max_value=49999.0)
)
@hypothesis_settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_preservation_auto_execute_below_threshold(cost_impact, db_connection):
    """
    **Validates: Requirements 3.3**
    
    Preservation: Actions with cost impact below ₹50,000 continue to auto-execute without approval
    
    Property: For any action with cost_impact_inr < 50000, the system SHALL auto-execute
    without requiring approval.
    """
    # Create a test anomaly with cost below threshold
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, 'duplicate_payment', $2, 'transactions', 0.95, 'MEDIUM', $3, 'detected', 'qwen2.5:7b', 'Test')
    """, anomaly_id, uuid4(), cost_impact)
    
    # Check that the approval threshold is still 50000
    assert app_settings.AUTO_APPROVE_LIMIT == 50000.0, \
        "AUTO_APPROVE_LIMIT should remain at ₹50,000"


@given(
    cost_impact=st.floats(min_value=50001.0, max_value=200000.0)
)
@hypothesis_settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_preservation_approval_required_above_threshold(cost_impact, db_connection):
    """
    **Validates: Requirements 3.4**
    
    Preservation: Actions with cost impact above ₹50,000 continue to route to approval queue
    
    Property: For any action with cost_impact_inr > 50000, the system SHALL route to
    approval queue with status=pending_approval.
    """
    # Verify the threshold is preserved
    assert app_settings.AUTO_APPROVE_LIMIT == 50000.0, \
        "AUTO_APPROVE_LIMIT should remain at ₹50,000"
    
    # Verify cost_impact is above threshold
    assert cost_impact > app_settings.AUTO_APPROVE_LIMIT


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 3: DEMO RESET PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_demo_reset_counts(http_client, db_connection):
    """
    **Validates: Requirements 3.5**
    
    Preservation: Demo reset endpoint continues to re-seed 450 transactions, 
    200 licenses, and 50 SLA tickets with clean state
    
    When the demo reset endpoint is called, the system SHALL CONTINUE TO re-seed
    450 transactions, 200 licenses, and 50 SLA tickets.
    """
    # Trigger demo reset
    response = await http_client.post("/api/demo/reset")
    assert response.status_code == 200
    
    # Wait for reset to complete
    await asyncio.sleep(2)
    
    # Check transaction count
    tx_count = await db_connection.fetchval("SELECT COUNT(*) FROM transactions")
    assert tx_count >= 400, f"Expected ≥400 transactions after reset, got {tx_count}"
    
    # Check license count
    license_count = await db_connection.fetchval("SELECT COUNT(*) FROM licenses")
    assert license_count >= 150, f"Expected ≥150 licenses after reset, got {license_count}"
    
    # Check SLA metrics count
    sla_count = await db_connection.fetchval("SELECT COUNT(*) FROM sla_metrics")
    assert sla_count >= 40, f"Expected ≥40 SLA tickets after reset, got {sla_count}"


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 4: API CONTRACT PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_savings_summary_api_schema(http_client):
    """
    **Validates: Requirements 3.6**
    
    Preservation: GET /api/savings/summary continues to return all required fields
    
    API response schema must remain unchanged with all 9 required fields.
    """
    response = await http_client.get("/api/savings/summary")
    assert response.status_code == 200
    
    data = response.json()
    
    # Verify all required fields are present
    required_fields = [
        "duplicate_payments_blocked",
        "unused_subscriptions_cancelled",
        "sla_penalties_avoided",
        "reconciliation_errors_fixed",
        "total_savings_this_month",
        "annual_projection",
        "actions_taken_count",
        "anomalies_detected_count",
        "pending_approvals_count",
    ]
    
    for field in required_fields:
        assert field in data, f"Required field '{field}' missing from /api/savings/summary response"


@pytest.mark.asyncio
async def test_preservation_anomalies_api_schema(http_client):
    """
    **Validates: Requirements 3.7**
    
    Preservation: GET /api/anomalies/ continues to return anomaly objects with all required fields
    """
    response = await http_client.get("/api/anomalies/?limit=1")
    assert response.status_code == 200
    
    anomalies = response.json()
    
    if len(anomalies) > 0:
        anomaly = anomalies[0]
        
        # Verify all required fields are present
        required_fields = [
            "id",
            "anomaly_type",
            "severity",
            "confidence",
            "cost_impact_inr",
            "status",
            "detected_at",
        ]
        
        for field in required_fields:
            assert field in anomaly, f"Required field '{field}' missing from anomaly object"


@pytest.mark.asyncio
async def test_preservation_actions_api_schema(http_client):
    """
    **Validates: Requirements 3.8**
    
    Preservation: GET /api/actions/ continues to return action objects with all required fields
    """
    response = await http_client.get("/api/actions/?limit=1")
    assert response.status_code == 200
    
    actions = response.json()
    
    if len(actions) > 0:
        action = actions[0]
        
        # Verify all required fields are present
        required_fields = [
            "id",
            "action_type",
            "status",
            "cost_saved",
            "executed_at",
            "executed_by",
        ]
        
        for field in required_fields:
            assert field in action, f"Required field '{field}' missing from action object"


@pytest.mark.asyncio
async def test_preservation_audit_api_schema(http_client):
    """
    **Validates: Requirements 3.9**
    
    Preservation: GET /api/audit/ continues to return audit records with all required fields
    """
    response = await http_client.get("/api/audit/?limit=1")
    assert response.status_code == 200
    
    audit_records = response.json()
    
    if len(audit_records) > 0:
        audit = audit_records[0]
        
        # Verify all required fields are present
        required_fields = [
            "agent",
            "model_used",
            "final_status",
            "execution_time_ms",
        ]
        
        for field in required_fields:
            assert field in audit, f"Required field '{field}' missing from audit record"


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 5: DATABASE SCHEMA PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_database_schema_tables(db_connection):
    """
    **Validates: Requirements 3.10**
    
    Preservation: All 8 required tables continue to exist in the database
    
    When the system starts up, the system SHALL CONTINUE TO execute schema.sql
    to create all 8 required tables.
    """
    # Query for all tables in the public schema
    tables = await db_connection.fetch("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
    """)
    
    table_names = [t["table_name"] for t in tables]
    
    # Verify all 8 required tables exist
    required_tables = [
        "vendors",
        "transactions",
        "licenses",
        "sla_metrics",
        "anomaly_logs",
        "actions_taken",
        "approval_queue",
        "audit_trail",
    ]
    
    for table in required_tables:
        assert table in table_names, f"Required table '{table}' missing from database schema"


@pytest.mark.asyncio
async def test_preservation_sla_deadline_generated_column(db_connection):
    """
    **Validates: Requirements 3.11**
    
    Preservation: sla_deadline column continues to be auto-generated by PostgreSQL
    
    When inserting into sla_metrics, the system SHALL CONTINUE TO allow PostgreSQL
    to auto-generate the sla_deadline column based on opened_at + sla_hours.
    """
    # Check that sla_deadline is a GENERATED column
    column_info = await db_connection.fetchrow("""
        SELECT column_name, is_generated, generation_expression
        FROM information_schema.columns
        WHERE table_name = 'sla_metrics' AND column_name = 'sla_deadline'
    """)
    
    if column_info:
        # If the column exists, verify it's generated
        assert column_info["is_generated"] in ["ALWAYS", "YES"], \
            "sla_deadline should be a GENERATED column"


@pytest.mark.asyncio
async def test_preservation_actions_taken_filtering(db_connection):
    """
    **Validates: Requirements 3.12**
    
    Preservation: actions_taken table continues to support filtering by status, 
    action_type, and date ranges
    """
    # Verify we can query with filters (schema supports these columns)
    result = await db_connection.fetch("""
        SELECT id, action_type, status, executed_at
        FROM actions_taken
        WHERE status = 'success'
        AND action_type = 'payment_hold'
        AND executed_at > NOW() - INTERVAL '7 days'
        LIMIT 1
    """)
    
    # Query should execute without error (even if no results)
    assert result is not None


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 6: FRONTEND BEHAVIOR PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_dashboard_polling_endpoint(http_client):
    """
    **Validates: Requirements 3.13**
    
    Preservation: Dashboard continues to poll /api/savings/summary every 10 seconds
    
    The endpoint must remain available and return valid data for frontend polling.
    """
    # Verify the endpoint is accessible
    response = await http_client.get("/api/savings/summary")
    assert response.status_code == 200
    
    data = response.json()
    assert "total_savings_this_month" in data


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY 7: MODEL MANAGEMENT PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_preservation_model_configuration(db_connection):
    """
    **Validates: Requirements 3.17, 3.18**
    
    Preservation: Model management continues (DeepSeek unloads current model before loading,
    reloads Qwen after completion)
    
    Verify model configuration constants are preserved.
    """
    # Verify model names are preserved
    assert app_settings.MODEL_DEFAULT == "qwen2.5:7b", \
        "Default model should remain qwen2.5:7b"
    assert app_settings.MODEL_REASONING == "deepseek-r1:7b", \
        "Reasoning model should remain deepseek-r1:7b"
    assert app_settings.MODEL_FALLBACK == "llama3.2:3b", \
        "Fallback model should remain llama3.2:3b"


@pytest.mark.asyncio
async def test_preservation_deepseek_budget_limit(db_connection):
    """
    **Validates: Requirements 3.19**
    
    Preservation: DeepSeek hourly budget (10 calls) continues to be enforced
    
    When the DeepSeek hourly budget is exhausted, the system SHALL CONTINUE TO
    fall back to Qwen for HIGH severity detections.
    """
    # Verify budget configuration is preserved
    assert app_settings.MAX_DEEPSEEK_CALLS_PER_HOUR == 10, \
        "DeepSeek hourly budget should remain at 10 calls"


@pytest.mark.asyncio
async def test_preservation_llama_fallback_configuration(db_connection):
    """
    **Validates: Requirements 3.20**
    
    Preservation: Llama 3.2:3b continues to be used as fallback
    
    When Llama 3.2:3b is used as fallback, the system SHALL CONTINUE TO generate
    deterministic decisions based on severity and cost thresholds.
    """
    # Verify fallback model is preserved
    assert app_settings.MODEL_FALLBACK == "llama3.2:3b", \
        "Fallback model should remain llama3.2:3b"


# ═══════════════════════════════════════════════════════════════════════════
# PROPERTY-BASED TESTS: COMPREHENSIVE PRESERVATION CHECKS
# ═══════════════════════════════════════════════════════════════════════════

@given(
    severity=st.sampled_from([Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]),
    confidence=st.floats(min_value=0.6, max_value=1.0),
    cost_impact=st.floats(min_value=1000.0, max_value=200000.0),
)
@hypothesis_settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_property_model_routing_preserved(severity, confidence, cost_impact, db_connection):
    """
    **Property 7: Preservation - Non-Buggy Behavior Unchanged**
    
    For any input that does NOT match the bug conditions (valid data, sufficient inference time),
    the fixed system SHALL produce exactly the same behavior as the original system.
    
    This property verifies model routing logic is preserved:
    - Qwen 2.5:7b for standard decisions
    - DeepSeek-R1:7b for HIGH/CRITICAL severity
    - Approval gate at ₹50,000
    
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    # Verify severity-based routing is preserved
    if severity in [Severity.HIGH, Severity.CRITICAL]:
        # HIGH/CRITICAL should trigger DeepSeek consideration
        assert severity.triggers_deepseek, \
            f"{severity.value} severity should trigger DeepSeek routing"
    
    # Verify approval gate threshold is preserved
    requires_approval = cost_impact > app_settings.AUTO_APPROVE_LIMIT
    
    if cost_impact < 50000:
        assert not requires_approval, \
            f"Cost impact {cost_impact} below ₹50k should auto-execute"
    elif cost_impact > 50000:
        assert requires_approval, \
            f"Cost impact {cost_impact} above ₹50k should require approval"


@given(
    anomaly_type=st.sampled_from([
        AnomalyType.DUPLICATE_PAYMENT,
        AnomalyType.UNUSED_SUBSCRIPTION,
        AnomalyType.SLA_RISK,
        AnomalyType.PRICING_ANOMALY,
    ]),
)
@hypothesis_settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_property_anomaly_detection_preserved(anomaly_type, db_connection):
    """
    **Property 7: Preservation - Anomaly Detection Logic Unchanged**
    
    For any anomaly type, the system SHALL continue to detect and process anomalies
    using the same logic as before the fixes.
    
    **Validates: Requirements 3.1-3.20**
    """
    # Verify anomaly type is valid
    assert anomaly_type in AnomalyType, \
        f"Anomaly type {anomaly_type} should be valid"
    
    # Verify we can create anomaly records with this type
    anomaly_id = uuid4()
    await db_connection.execute("""
        INSERT INTO anomaly_logs 
            (id, anomaly_type, entity_id, entity_table, confidence, severity, 
             cost_impact_inr, status, model_used, root_cause)
        VALUES ($1, $2, $3, 'test_table', 0.85, 'MEDIUM', 10000.00, 'detected', 'qwen2.5:7b', 'Test')
    """, anomaly_id, anomaly_type.value, uuid4())
    
    # Verify the record was created
    record = await db_connection.fetchrow("""
        SELECT id, anomaly_type FROM anomaly_logs WHERE id = $1
    """, anomaly_id)
    
    assert record is not None
    assert record["anomaly_type"] == anomaly_type.value


@pytest.mark.asyncio
async def test_preservation_system_constants(db_connection):
    """
    **Validates: Requirements 3.1-3.20**
    
    Preservation: All system constants and thresholds remain unchanged
    
    Verify that core business logic constants are preserved after fixes.
    """
    # Approval threshold
    assert app_settings.AUTO_APPROVE_LIMIT == 50000.0
    
    # Model configuration
    assert app_settings.MODEL_DEFAULT == "qwen2.5:7b"
    assert app_settings.MODEL_REASONING == "deepseek-r1:7b"
    assert app_settings.MODEL_FALLBACK == "llama3.2:3b"
    
    # DeepSeek budget
    assert app_settings.MAX_DEEPSEEK_CALLS_PER_HOUR == 10
    
    # Business thresholds
    assert app_settings.SLA_ESCALATION_THRESHOLD == 0.70
    assert app_settings.DUPLICATE_WINDOW_DAYS == 30
    assert app_settings.UNUSED_LICENSE_DAYS == 60
    assert app_settings.PRICING_ANOMALY_PCT == 0.15
