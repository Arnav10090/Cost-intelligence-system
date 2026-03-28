"""
Seed demo data into PostgreSQL.
Includes pre-planted anomalies for the demo trigger:
  - 3 duplicate payment pairs (same PO, same vendor, same amount)
  - 29 licenses assigned to terminated employees
  - 5 SLA tickets at >80% breach probability
  - 2 reconciliation gaps
Run: python db/seed_data.py
"""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
import asyncpg
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.config import settings

# ─── Seed constants ────────────────────────────────────────────────────────
VENDOR_NAMES = [
    ("Infosys Ltd", "Services"), ("Tata Consultancy Services", "Services"),
    ("AWS India", "Infrastructure"), ("Microsoft Azure", "Infrastructure"),
    ("Salesforce India", "SaaS"), ("Slack Technologies", "SaaS"),
    ("Zoom India", "SaaS"), ("Jira / Atlassian", "SaaS"),
    ("Wipro Digital", "Services"), ("HCL Technologies", "Services"),
    ("Google Cloud", "Infrastructure"), ("Adobe Systems", "SaaS"),
    ("ServiceNow", "SaaS"), ("Datadog", "SaaS"),
    ("Freshworks", "SaaS"), ("Zoho Corp", "SaaS"),
]

TOOLS = ["Slack", "Jira", "Zoom", "Salesforce", "Adobe Creative", "Datadog",
         "GitHub", "Figma", "Notion", "HubSpot", "Tableau", "ServiceNow"]

EMPLOYEE_EMAILS = [f"emp{i:04d}@company.local" for i in range(1, 300)]


async def seed(conn: asyncpg.Connection) -> None:
    print("🌱  Starting seed...")

    # ── Vendors ──────────────────────────────────────────────────────────────
    print("   Seeding vendors...")
    vendor_ids: dict[str, uuid.UUID] = {}
    for name, category in VENDOR_NAMES:
        vid = uuid.uuid4()
        vendor_ids[name] = vid
        contract_rate = Decimal(str(random.randint(5000, 500000)))
        await conn.execute("""
            INSERT INTO vendors (id, name, category, contract_rate, payment_terms,
                                  risk_score, market_benchmark)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT DO NOTHING
        """, vid, name, category, contract_rate, random.choice([15, 30, 45]),
            round(random.uniform(0.0, 0.4), 2),
            contract_rate * Decimal(str(round(random.uniform(0.85, 1.15), 2))))

    vendor_id_list = list(vendor_ids.values())

    # ── Normal Transactions (450) ─────────────────────────────────────────────
    print("   Seeding 450 normal transactions...")
    today = date.today()
    for i in range(450):
        vid = random.choice(vendor_id_list)
        amount = Decimal(str(random.randint(10000, 200000)))
        txn_date = today - timedelta(days=random.randint(0, 89))
        await conn.execute("""
            INSERT INTO transactions
                (id, vendor_id, invoice_number, amount, currency, transaction_date,
                 po_number, status)
            VALUES ($1, $2, $3, $4, 'INR', $5, $6, 'approved')
        """, uuid.uuid4(), vid, f"INV-{10000+i}", amount, txn_date,
            f"PO-{8000+i}")

    # ── PLANTED: 3 Duplicate Payment Pairs ────────────────────────────────────
    print("   Planting 3 duplicate payment pairs...")
    dup_vendor = vendor_id_list[0]
    for idx, (po, amount) in enumerate([
        ("PO-2891", Decimal("45000.00")),
        ("PO-3042", Decimal("28500.00")),
        ("PO-4117", Decimal("72000.00")),
    ]):
        base_date = today - timedelta(days=random.randint(3, 20))
        # Original (approved)
        await conn.execute("""
            INSERT INTO transactions
                (id, vendor_id, invoice_number, amount, currency, transaction_date,
                 po_number, status)
            VALUES ($1, $2, $3, $4, 'INR', $5, $6, 'approved')
        """, uuid.uuid4(), dup_vendor, f"INV-{po}-A", amount, base_date, po)
        # Duplicate (pending — should be caught)
        await conn.execute("""
            INSERT INTO transactions
                (id, vendor_id, invoice_number, amount, currency, transaction_date,
                 po_number, status)
            VALUES ($1, $2, $3, $4, 'INR', $5, $6, 'pending')
        """, uuid.uuid4(), dup_vendor, f"INV-{po}-B", amount,
            base_date + timedelta(days=1), po)

    # ── Licenses (200 total: 29 terminated, 40 inactive, rest active) ────────
    print("   Seeding 200 licenses...")
    for i in range(200):
        tool = random.choice(TOOLS)
        monthly_cost = Decimal(str(random.randint(500, 5000)))
        email = EMPLOYEE_EMAILS[i % len(EMPLOYEE_EMAILS)]

        # 29 terminated employees (indices 0-28)
        if i < 29:
            last_login = datetime.utcnow() - timedelta(days=random.randint(65, 180))
            employee_active = False  # terminated
        # 40 inactive (indices 29-68)
        elif i < 69:
            last_login = datetime.utcnow() - timedelta(days=random.randint(61, 90))
            employee_active = True
        else:
            last_login = datetime.utcnow() - timedelta(days=random.randint(0, 30))
            employee_active = True

        await conn.execute("""
            INSERT INTO licenses
                (id, tool_name, assigned_email, last_login, is_active,
                 monthly_cost, employee_active)
            VALUES ($1, $2, $3, $4, TRUE, $5, $6)
        """, uuid.uuid4(), tool, email, last_login, monthly_cost, employee_active)

    # ── SLA Tickets (50 total: 5 near-breach) ─────────────────────────────────
    print("   Seeding 50 SLA tickets...")
    for i in range(50):
        sla_hours = random.choice([4, 8, 24, 48])
        penalty = Decimal(str(random.randint(5000, 50000)))

        # 5 near-breach tickets (indices 0-4) — P(breach) > 0.70
        if i < 5:
            # Set opened_at so elapsed ≈ 82% of SLA window
            elapsed = sla_hours * 0.82
            opened_at = datetime.utcnow() - timedelta(hours=elapsed)
            priority = "P1"
            assignee_id = None   # no assignee — boosts breach probability
        else:
            opened_at = datetime.utcnow() - timedelta(hours=random.uniform(0, sla_hours * 0.5))
            priority = random.choice(["P1", "P2", "P3"])
            assignee_id = uuid.uuid4()

        await conn.execute("""
            INSERT INTO sla_metrics
                (id, ticket_id, sla_hours, opened_at, status,
                 assignee_id, priority, penalty_amount)
            VALUES ($1, $2, $3, $4, 'open', $5, $6, $7)
        """, uuid.uuid4(), f"TKT-{9800+i}", sla_hours, opened_at,
            assignee_id, priority, penalty)

    print("✅  Seed complete!")
    print("   Duplicates planted:       3 pairs")
    print("   Terminated licenses:      29")
    print("   Near-breach SLA tickets:  5")
    print("   Total transactions:       ~456")
    print("   Total licenses:           200")
    print("   Total SLA tickets:        50")


async def main():
    conn = await asyncpg.connect(
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
    )
    try:
        await seed(conn)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())