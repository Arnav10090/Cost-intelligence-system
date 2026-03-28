"""
pytest configuration and shared fixtures.

Key fixtures:
  db          — async asyncpg connection to a test schema (rolled back after each test)
  client      — FastAPI AsyncClient with mocked Ollama
  mock_ollama — patches llm_router so no real Ollama calls happen in tests
  seed_db     — lightweight fixture that inserts minimal test data
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ── Point at test database ─────────────────────────────────────────────────────
os.environ.setdefault("POSTGRES_DB", "cost_intelligence_test")
os.environ.setdefault("POSTGRES_USER", "ci_user")
os.environ.setdefault("POSTGRES_PASSWORD", "ci_pass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "WARNING")


# ── Event loop (session-scoped) ────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Raw DB connection (transaction-rolled-back per test) ──────────────────────
@pytest_asyncio.fixture(scope="session")
async def db_pool():
    """Create a connection pool to the test DB once per session."""
    pool = await asyncpg.create_pool(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        min_size=2,
        max_size=5,
    )

    # Apply schema
    with open("db/schema.sql") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)

    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def db(db_pool) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Per-test isolated connection wrapped in a transaction that is
    always rolled back — leaves the DB clean for the next test.
    """
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        yield conn
        await tr.rollback()


# ── FastAPI test client with mocked Ollama ─────────────────────────────────────
@pytest_asyncio.fixture
async def client(mock_ollama) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient bound to the FastAPI app with Ollama mocked out."""
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Mock Ollama (no real LLM calls in unit tests) ─────────────────────────────
@pytest.fixture
def mock_ollama():
    """
    Patch llm_router.infer so tests don't need a running Ollama instance.
    Default response is a valid qwen2.5:7b JSON stub.
    """
    from core.constants import ModelName

    default_response = json.dumps({
        "root_cause": "Test duplicate billing — same PO, 2 invoices",
        "confidence": 0.97,
        "action": "hold_payment",
        "action_details": {"invoice_id": str(uuid.uuid4()), "hold_reason": "Duplicate PO"},
        "cost_impact_inr": 45000,
        "urgency": "HIGH",
        "reasoning_chain": ["Step 1: Same PO detected", "Step 2: Same amount within 30 days"],
    })

    with patch("services.llm_router.infer", new_callable=AsyncMock) as mock:
        mock.return_value = (default_response, ModelName.QWEN)
        yield mock


@pytest.fixture
def mock_deepseek():
    """Patch infer to return a deepseek-r1 response for high-severity tests."""
    from core.constants import ModelName

    response = json.dumps({
        "root_cause": "Vendor duplicate billing — PO reused across two invoice IDs",
        "confidence": 0.94,
        "action": "hold_payment",
        "action_details": {"hold_reason": "Duplicate PO confirmed by deepseek-r1"},
        "cost_impact_inr": 45000,
        "urgency": "HIGH",
        "reasoning_chain": [
            "Step 1: Both invoices share PO-2891",
            "Step 2: Timestamps 24h apart — likely billing lag",
            "Step 3: No authorised amendment found in history",
        ],
    })

    with patch("services.llm_router.infer", new_callable=AsyncMock) as mock:
        mock.return_value = (response, ModelName.DEEPSEEK)
        yield mock


# ── Minimal seed data ─────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def seed_db(db: asyncpg.Connection):
    """
    Insert a minimal, deterministic dataset for unit tests.
    Much faster than the full 500-row seeder.
    """
    # Vendor
    vendor_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO vendors (id, name, category, contract_rate, market_benchmark)
        VALUES ($1, 'Test Vendor Ltd', 'Services', 50000.00, 45000.00)
    """, vendor_id)

    today = datetime.now(timezone.utc).date()

    # Normal transaction
    txn_a_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO transactions
            (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
        VALUES ($1, $2, 'INV-ORIG-001', 45000.00, $3, 'PO-TEST-001', 'approved')
    """, txn_a_id, vendor_id, today - timedelta(days=1))

    # Duplicate transaction (same PO, same amount, next day)
    txn_b_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO transactions
            (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
        VALUES ($1, $2, 'INV-DUP-001', 45000.00, $3, 'PO-TEST-001', 'pending')
    """, txn_b_id, vendor_id, today)

    # License — terminated employee (confident unused)
    lic_terminated_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO licenses
            (id, tool_name, assigned_email, last_login, is_active, monthly_cost, employee_active)
        VALUES ($1, 'Slack', 'ex.employee@company.local',
                NOW() - INTERVAL '90 days', TRUE, 3000.00, FALSE)
    """, lic_terminated_id)

    # License — inactive 65 days (active employee, just not using it)
    lic_inactive_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO licenses
            (id, tool_name, assigned_email, last_login, is_active, monthly_cost, employee_active)
        VALUES ($1, 'Zoom', 'active.user@company.local',
                NOW() - INTERVAL '65 days', TRUE, 2000.00, TRUE)
    """, lic_inactive_id)

    # SLA ticket — near breach (P1, no assignee, 82% elapsed)
    await db.execute("""
        INSERT INTO sla_metrics
            (id, ticket_id, sla_hours, opened_at, status, priority, penalty_amount)
        VALUES ($1, 'TKT-TEST-001', 4,
                NOW() - INTERVAL '3.3 hours', 'open', 'P1', 25000.00)
    """, uuid.uuid4())

    # SLA ticket — safe (P3, has assignee, 20% elapsed)
    await db.execute("""
        INSERT INTO sla_metrics
            (id, ticket_id, sla_hours, opened_at, status, assignee_id, priority, penalty_amount)
        VALUES ($1, 'TKT-TEST-002', 24,
                NOW() - INTERVAL '4 hours', 'open', $2, 'P3', 5000.00)
    """, uuid.uuid4(), uuid.uuid4())

    return {
        "vendor_id": vendor_id,
        "txn_original_id": txn_a_id,
        "txn_duplicate_id": txn_b_id,
        "lic_terminated_id": lic_terminated_id,
        "lic_inactive_id": lic_inactive_id,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_anomaly_id(db: asyncpg.Connection, **kwargs) -> uuid.UUID:
    """Convenience — insert a test anomaly_log row and return its id."""
    pass  # implemented inline in individual tests for clarity