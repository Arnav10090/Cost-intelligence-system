"""
Demo router — blueprint §14.
Powers the "Simulate Cost Leak" button in the dashboard.

POST /api/demo/trigger?scenario=<name>  — injects a scripted anomaly scenario
GET  /api/demo/status/{task_id}         — poll for pipeline completion
GET  /api/demo/scenarios                — list available demo scenarios
POST /api/demo/reset                    — truncates + re-seeds demo data
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from core.constants import TaskType
from db.database import get_db

router = APIRouter(prefix="/api/demo", tags=["demo"])

# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════
SCENARIOS = [
    {
        "id": "duplicate_payment",
        "title": "Duplicate Payment",
        "description": "Inject ₹1,00,000 duplicate with same PO → detect → hold → audit",
        "amount_display": "₹1,00,000",
        "icon": "💳",
        "severity": "HIGH",
    },
    {
        "id": "sla_breach",
        "title": "SLA Near-Breach",
        "description": "Inject P1 ticket 3.3h into 4h SLA (no assignee) → escalate",
        "amount_display": "₹25,000 penalty",
        "icon": "⏱️",
        "severity": "CRITICAL",
    },
    {
        "id": "unused_subscriptions",
        "title": "Unused Subscriptions",
        "description": "Inject 5 licenses for non-existent employees → bulk deactivate",
        "amount_display": "₹15,000/month",
        "icon": "🔑",
        "severity": "MEDIUM",
    },
    {
        "id": "approval_queue",
        "title": "Approval Queue",
        "description": "Inject ₹75,000 duplicate (above ₹50k limit) → needs approval",
        "amount_display": "₹75,000",
        "icon": "✅",
        "severity": "HIGH",
    },
]


@router.get("/scenarios")
async def list_scenarios():
    """List all available demo scenarios for the frontend selector."""
    return {"scenarios": SCENARIOS}


# ═══════════════════════════════════════════════════════════════════════════
# TRIGGER ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/trigger")
async def trigger_demo(
    scenario: str = Query("duplicate_payment", description="Demo scenario to run"),
    db: asyncpg.Connection = Depends(get_db),
):
    """
    Injects a pre-scripted scenario into the live system.
    Supported scenarios: duplicate_payment, sla_breach, unused_subscriptions, approval_queue
    """
    valid_ids = {s["id"] for s in SCENARIOS}
    if scenario not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Valid: {sorted(valid_ids)}",
        )

    dispatch = {
        "duplicate_payment": _inject_duplicate_payment,
        "sla_breach": _inject_sla_breach,
        "unused_subscriptions": _inject_unused_subscriptions,
        "approval_queue": _inject_approval_queue,
    }

    result = await dispatch[scenario](db)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 1 — Duplicate Payment (primary demo)
# ═══════════════════════════════════════════════════════════════════════════
async def _inject_duplicate_payment(db: asyncpg.Connection) -> dict:
    """
    Insert ₹1,00,000 duplicate payment pair with same PO.
    Expected: Detected <2s, deepseek reasons, payment held, email sent, audit written.
    Dashboard: savings counter increments by ₹1,00,000 live.
    """
    task_id = str(uuid.uuid4())
    today = date.today()

    vendor_id = await _ensure_demo_vendor(db)

    # Original approved transaction (idempotent)
    orig_id = uuid.uuid4()
    existing = await db.fetchval(
        "SELECT id FROM transactions WHERE po_number = 'PO-DEMO-001' AND status = 'approved' LIMIT 1"
    )
    if not existing:
        await db.execute("""
            INSERT INTO transactions
                (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
            VALUES ($1, $2, 'INV-DEMO-ORIG', 100000.00, $3, 'PO-DEMO-001', 'approved')
        """, orig_id, vendor_id, today)
    else:
        orig_id = existing

    # Duplicate pending transaction
    dup_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO transactions
            (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
        VALUES ($1, $2, $3, 100000.00, $4, 'PO-DEMO-001', 'pending')
    """, dup_id, vendor_id, f"INV-DEMO-DUP-{task_id[:8]}", today)

    await _publish_task(task_id, TaskType.DEMO_TRIGGER, "HIGH", {
        "scenario": "duplicate_payment",
        "vendor_id": str(vendor_id),
        "original_txn_id": str(orig_id),
        "duplicate_txn_id": str(dup_id),
        "amount": 100000,
        "po": "PO-DEMO-001",
    })

    return {
        "task_id": task_id,
        "message": "Demo scenario injected — pipeline processing",
        "scenario": "duplicate_payment",
        "amount_inr": 100000,
        "po_number": "PO-DEMO-001",
        "duplicate_txn_id": str(dup_id),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 2 — SLA Near-Breach
# ═══════════════════════════════════════════════════════════════════════════
async def _inject_sla_breach(db: asyncpg.Connection) -> dict:
    """
    Inject: Ticket TKT-DEMO-001, P1, 4h SLA, opened 3.3h ago, no assignee.
    Expected: P(breach) ≈ 0.85, escalated, email sent.
    Dashboard: anomaly feed shows new entry, actions panel shows escalation.
    """
    task_id = str(uuid.uuid4())
    ticket_id_str = f"TKT-DEMO-{task_id[:6].upper()}"

    # Delete any previous demo SLA ticket to keep it clean
    await db.execute(
        "DELETE FROM sla_metrics WHERE ticket_id LIKE 'TKT-DEMO-%'"
    )

    now = datetime.now(timezone.utc)
    opened_at = now - timedelta(hours=3.3)
    sla_ticket_id = uuid.uuid4()

    await db.execute("""
        INSERT INTO sla_metrics
            (id, ticket_id, sla_hours, opened_at, status, assignee_id,
             priority, penalty_amount, breach_prob)
        VALUES ($1, $2, 4, $3, 'open', NULL, 'P1', 25000.00, 0.0)
    """, sla_ticket_id, ticket_id_str, opened_at)

    await _publish_task(task_id, TaskType.SCAN_SLA, "HIGH", {
        "scenario": "sla_breach",
        "ticket_id": ticket_id_str,
        "sla_ticket_db_id": str(sla_ticket_id),
        "sla_hours": 4,
        "elapsed_hours": 3.3,
        "penalty_amount": 25000,
    })

    return {
        "task_id": task_id,
        "message": "SLA near-breach scenario injected — pipeline processing",
        "scenario": "sla_breach",
        "ticket_id": ticket_id_str,
        "sla_hours": 4,
        "elapsed_hours": 3.3,
        "penalty_amount_inr": 25000,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 3 — Unused Subscriptions
# ═══════════════════════════════════════════════════════════════════════════
async def _inject_unused_subscriptions(db: asyncpg.Connection) -> dict:
    """
    Inject: 5 licenses for non-existent employees.
    Expected: All 5 deactivated, ₹15,000/month saved shown.
    Dashboard: actions panel shows bulk deactivation.
    """
    task_id = str(uuid.uuid4())

    # Clean up previous demo licenses
    await db.execute(
        "DELETE FROM licenses WHERE assigned_email LIKE 'demo-ghost-%'"
    )

    license_ids = []
    tools = ["Slack", "Jira", "Zoom", "Figma", "Notion"]
    total_monthly = Decimal("0.00")
    now = datetime.now(timezone.utc)

    for i, tool in enumerate(tools):
        lic_id = uuid.uuid4()
        monthly_cost = Decimal("3000.00")  # ₹3,000 each = ₹15,000 total
        total_monthly += monthly_cost
        license_ids.append(str(lic_id))

        await db.execute("""
            INSERT INTO licenses
                (id, tool_name, assigned_email, last_login, is_active,
                 monthly_cost, employee_active)
            VALUES ($1, $2, $3, $4, TRUE, $5, FALSE)
        """, lic_id, tool,
            f"demo-ghost-{i+1}@company.local",
            now - timedelta(days=120 + i * 10),   # last login 120-160 days ago
            monthly_cost)

    await _publish_task(task_id, TaskType.SCAN_LICENSES, "NORMAL", {
        "scenario": "unused_subscriptions",
        "license_ids": license_ids,
        "total_monthly_cost": float(total_monthly),
        "count": 5,
    })

    return {
        "task_id": task_id,
        "message": "Unused subscriptions scenario injected — pipeline processing",
        "scenario": "unused_subscriptions",
        "licenses_injected": 5,
        "monthly_savings_inr": float(total_monthly),
        "license_ids": license_ids,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 4 — Approval Queue Demo
# ═══════════════════════════════════════════════════════════════════════════
async def _inject_approval_queue(db: asyncpg.Connection) -> dict:
    """
    Inject: Duplicate payment of ₹75,000 (above ₹50,000 auto-approve limit).
    Expected: Goes to approval queue, NOT auto-executed.
    Demo: Presenter clicks Approve in UI → action executes live.
    """
    task_id = str(uuid.uuid4())
    today = date.today()

    vendor_id = await _ensure_demo_vendor(db)

    # Original approved transaction
    orig_id = uuid.uuid4()
    existing = await db.fetchval(
        "SELECT id FROM transactions WHERE po_number = 'PO-DEMO-APPROVE' AND status = 'approved' LIMIT 1"
    )
    if not existing:
        await db.execute("""
            INSERT INTO transactions
                (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
            VALUES ($1, $2, 'INV-DEMO-APR-ORIG', 75000.00, $3, 'PO-DEMO-APPROVE', 'approved')
        """, orig_id, vendor_id, today)
    else:
        orig_id = existing

    # Duplicate — this one should trigger approval queue (₹75k > ₹50k limit)
    dup_id = uuid.uuid4()
    await db.execute("""
        INSERT INTO transactions
            (id, vendor_id, invoice_number, amount, transaction_date, po_number, status)
        VALUES ($1, $2, $3, 75000.00, $4, 'PO-DEMO-APPROVE', 'pending')
    """, dup_id, vendor_id, f"INV-DEMO-APR-DUP-{task_id[:8]}", today)

    await _publish_task(task_id, TaskType.DEMO_TRIGGER, "HIGH", {
        "scenario": "approval_queue",
        "vendor_id": str(vendor_id),
        "original_txn_id": str(orig_id),
        "duplicate_txn_id": str(dup_id),
        "amount": 75000,
        "po": "PO-DEMO-APPROVE",
    })

    return {
        "task_id": task_id,
        "message": "Approval queue scenario injected — awaiting human approval",
        "scenario": "approval_queue",
        "amount_inr": 75000,
        "po_number": "PO-DEMO-APPROVE",
        "duplicate_txn_id": str(dup_id),
        "note": "Amount ₹75,000 exceeds ₹50,000 auto-approve limit → goes to approval queue",
    }


# ═══════════════════════════════════════════════════════════════════════════
# STATUS POLL
# ═══════════════════════════════════════════════════════════════════════════
@router.get("/status/{task_id}")
async def demo_status(task_id: str, db: asyncpg.Connection = Depends(get_db)):
    """Poll for pipeline completion by task_id."""
    # Check audit_trail for a record with this task_id in input_data
    row = await db.fetchrow("""
        SELECT audit_id, final_status, action_taken, cost_impact_inr, timestamp
        FROM audit_trail
        WHERE input_data::text LIKE $1
        ORDER BY timestamp DESC
        LIMIT 1
    """, f"%{task_id}%")

    if not row:
        # Check if the anomaly was at least detected
        anomaly = await db.fetchrow("""
            SELECT id, status, cost_impact_inr FROM anomaly_logs
            ORDER BY detected_at DESC LIMIT 1
        """)
        if anomaly:
            return {
                "task_id": task_id,
                "status": "processing",
                "message": "Anomaly detected — action executing",
            }
        return {"task_id": task_id, "status": "queued", "message": "Pipeline queued"}

    return {
        "task_id": task_id,
        "status": dict(row)["final_status"],
        "audit_id": dict(row)["audit_id"],
        "cost_impact_inr": float(dict(row)["cost_impact_inr"] or 0),
        "completed_at": dict(row)["timestamp"].isoformat() if dict(row)["timestamp"] else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# RESET
# ═══════════════════════════════════════════════════════════════════════════
@router.post("/reset")
async def reset_demo(db: asyncpg.Connection = Depends(get_db)):
    """
    Truncate all transactional tables and re-seed demo data.
    Equivalent to scripts/reset_demo.sh but via HTTP.
    """
    tables = [
        "audit_trail", "actions_taken", "approval_queue",
        "anomaly_logs",
        "transactions", "licenses", "sla_metrics", "vendors",
    ]
    for table in tables:
        await db.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")

    # Re-seed
    from db.seed_data import seed
    await seed(db)

    return {
        "status": "ok",
        "message": "Demo data reset — 450 transactions, 200 licenses, 50 SLA tickets re-seeded",
    }


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def _ensure_demo_vendor(db: asyncpg.Connection) -> uuid.UUID:
    """Find or create the shared demo vendor."""
    vendor = await db.fetchrow(
        "SELECT id FROM vendors WHERE name = 'Demo Vendor Ltd' LIMIT 1"
    )
    if not vendor:
        vendor = await db.fetchrow("""
            INSERT INTO vendors (id, name, category, contract_rate, market_benchmark)
            VALUES ($1, 'Demo Vendor Ltd', 'Services', 100000.00, 90000.00)
            RETURNING id
        """, uuid.uuid4())
    return vendor["id"]


async def _publish_task(
    task_id: str,
    task_type: TaskType,
    priority: str,
    payload: dict,
) -> None:
    """Publish an AgentTask to Redis. Silently ignores Redis failures."""
    try:
        from services.redis_client import publish_task
        from models.schemas import AgentTask
        task = AgentTask(
            task_id=task_id,
            task_type=task_type.value,
            priority=priority,
            payload=payload,
        )
        await publish_task(task)
    except Exception:
        # Redis unavailable — data is seeded, pipeline won't run automatically
        pass
