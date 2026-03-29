"""
Anomaly Detection Agent — blueprint §6.

Runs detection algorithms, scores each finding (0.0–1.0 confidence),
and returns DetectionResult objects. Does NOT make LLM calls — pure
SQL + algorithmic logic. The Orchestrator decides whether to escalate
to the Decision Agent.

Detection methods:
  scan_duplicates()   — blueprint §6A: hash-based window matching
  scan_sla()          — blueprint §6C: sigmoid breach probability
  scan_licenses()     — blueprint §6B: terminated/inactive detection
  scan_pricing()      — >15% above vendor benchmark
"""
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

import asyncpg

from agents.base_agent import BaseAgent
from agents.interfaces import DetectionResult
from core.constants import (
    AgentName, AnomalyType, Confidence, ModelName, Severity, TaskType,
)
from core.utils import (
    levenshtein, normalize_invoice, sla_breach_probability, utcnow,
)
from models.schemas import AgentTask

logger = logging.getLogger(__name__)


class AnomalyDetectionAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.ANOMALY, db)

    # ── Router ────────────────────────────────────────────────────────────
    async def run(self, task: AgentTask) -> list[DetectionResult]:
        self._start_timer()
        task_type = task.task_type

        if task_type == TaskType.SCAN_DUPLICATES.value:
            return await self.scan_duplicates()
        elif task_type == TaskType.SCAN_SLA.value:
            return await self.scan_sla()
        elif task_type == TaskType.SCAN_LICENSES.value:
            return await self.scan_licenses()
        elif task_type == TaskType.SCAN_PRICING.value:
            return await self.scan_pricing()
        elif task_type == TaskType.RECONCILE.value:
            return await self.scan_reconciliation()
        elif task_type == TaskType.DEMO_TRIGGER.value:
            return await self.scan_duplicates()
        else:
            logger.warning("Unknown task type: %s", task_type)
            return []

    # ══════════════════════════════════════════════════════════════════════
    # FORMULA §6A — Duplicate Payment Detection
    # ══════════════════════════════════════════════════════════════════════
    async def scan_duplicates(self) -> list[DetectionResult]:
        """
        Blueprint §6A: Hash-based window matching with fuzzy vendor name comparison.
        Window: same vendor + amount ±2% + within 30 days.
        Confidence tiers:
          0.97 — same PO number (near-certain duplicate)
          0.82 — levenshtein(invoice_a, invoice_b) <= 2
          0.65 — amount + vendor match only
        Only flag if confidence > 0.60.
        """
        self._start_timer()
        results = []

        # Find candidate pairs: same vendor, similar amount, close dates, different IDs
        rows = await self.db.fetch("""
            SELECT
                t1.id            AS t1_id,
                t1.invoice_number AS t1_invoice,
                t1.po_number      AS t1_po,
                t1.amount         AS t1_amount,
                t1.transaction_date AS t1_date,
                t2.id            AS t2_id,
                t2.invoice_number AS t2_invoice,
                t2.po_number      AS t2_po,
                t2.amount         AS t2_amount,
                t2.transaction_date AS t2_date,
                v.name           AS vendor_name,
                t1.vendor_id
            FROM transactions t1
            JOIN transactions t2 ON (
                t1.vendor_id = t2.vendor_id
                AND t1.id < t2.id
                AND ABS(t1.amount - t2.amount) / NULLIF(t1.amount, 0) < 0.02
                AND t2.transaction_date BETWEEN
                    t1.transaction_date - INTERVAL '30 days'
                    AND t1.transaction_date + INTERVAL '30 days'
            )
            JOIN vendors v ON t1.vendor_id = v.id
            WHERE t1.status IN ('approved', 'pending')
              AND t2.status IN ('approved', 'pending')
              AND t2.id NOT IN (
                SELECT al.entity_id FROM anomaly_logs al
                JOIN actions_taken at ON al.id = at.anomaly_id
                WHERE al.anomaly_type = 'duplicate_payment'
                AND at.status IN ('success', 'pending_approval', 'approved')
                AND at.action_type = 'payment_hold'
              )
        """)

        seen_pairs: set[frozenset] = set()

        for row in rows:
            pair_key = frozenset([str(row["t1_id"]), str(row["t2_id"])])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # Determine confidence tier
            if (row["t1_po"] and row["t2_po"]
                    and row["t1_po"].strip() == row["t2_po"].strip()):
                confidence = Confidence.DUPLICATE_SAME_PO          # 0.97
            elif levenshtein(
                normalize_invoice(row["t1_invoice"] or ""),
                normalize_invoice(row["t2_invoice"] or ""),
            ) <= 2:
                confidence = Confidence.DUPLICATE_SIMILAR_INVOICE   # 0.82
            else:
                confidence = Confidence.DUPLICATE_AMOUNT_VENDOR     # 0.65

            if confidence <= Confidence.DUPLICATE_MIN_FLAG:
                continue

            severity = (
                Severity.HIGH if confidence >= 0.90
                else Severity.MEDIUM if confidence >= 0.70
                else Severity.LOW
            )

            results.append(DetectionResult(
                agent=self.name,
                model_used=ModelName.QWEN,
                elapsed_ms=self._elapsed_ms(),
                success=True,
                anomaly_type=AnomalyType.DUPLICATE_PAYMENT,
                entity_id=row["t2_id"],            # the newer (likely duplicate) invoice
                entity_table="transactions",
                confidence=confidence,
                severity=severity,
                cost_impact_inr=Decimal(str(row["t2_amount"])),
                evidence={
                    "original_id": str(row["t1_id"]),
                    "duplicate_id": str(row["t2_id"]),
                    "original_invoice": row["t1_invoice"],
                    "duplicate_invoice": row["t2_invoice"],
                    "po_number": row["t1_po"],
                    "amount": float(row["t2_amount"]),
                    "vendor_name": row["vendor_name"],
                    "vendor_id": str(row["vendor_id"]),
                    "days_apart": abs(
                        (row["t2_date"] - row["t1_date"]).days
                    ),
                },
            ))

        self.logger.info(
            "scan_duplicates: %d candidates → %d flagged (%.0fms)",
            len(rows), len(results), self._elapsed_ms(),
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # FORMULA §6C — SLA Breach Prediction
    # ══════════════════════════════════════════════════════════════════════
    async def scan_sla(self) -> list[DetectionResult]:
        """
        Blueprint §6C: sigmoid-based breach probability.
        Trigger at P(breach) >= SLA_ESCALATION_THRESHOLD (0.70).
        """
        from core.config import settings
        from action_handlers.sla_handler import (
            get_at_risk_tickets, update_breach_probability,
        )

        self._start_timer()
        results = []
        tickets = await get_at_risk_tickets(self.db)

        for ticket in tickets:
            elapsed = float(ticket.get("elapsed_hours", 0) or 0)
            sla_h   = int(ticket["sla_hours"])
            priority = ticket.get("priority", "P2")
            assignee = ticket.get("assignee_id")

            p_breach = sla_breach_probability(
                elapsed_hours=elapsed,
                sla_hours=sla_h,
                has_assignee=bool(assignee),
                priority=priority,
                status=ticket.get("status", "open"),
            )

            # Update stored probability
            await update_breach_probability(
                self.db, ticket["ticket_id"], p_breach
            )

            if p_breach < settings.SLA_ESCALATION_THRESHOLD:
                continue

            severity = (
                Severity.CRITICAL if p_breach >= 0.90
                else Severity.HIGH if p_breach >= 0.75
                else Severity.MEDIUM
            )

            results.append(DetectionResult(
                agent=self.name,
                model_used=ModelName.QWEN,
                elapsed_ms=self._elapsed_ms(),
                success=True,
                anomaly_type=AnomalyType.SLA_RISK,
                entity_id=ticket["id"],
                entity_table="sla_metrics",
                confidence=round(p_breach, 4),
                severity=severity,
                cost_impact_inr=Decimal(str(ticket["penalty_amount"])),
                evidence={
                    "ticket_id": ticket["ticket_id"],
                    "sla_hours": sla_h,
                    "elapsed_hours": round(elapsed, 2),
                    "breach_probability": round(p_breach, 4),
                    "has_assignee": bool(assignee),
                    "priority": priority,
                    "penalty_amount": float(ticket["penalty_amount"]),
                    "sla_deadline": str(ticket["sla_deadline"]),
                },
            ))

        self.logger.info(
            "scan_sla: %d open tickets → %d at risk (%.0fms)",
            len(tickets), len(results), self._elapsed_ms(),
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # FORMULA §6B — Unused Subscription Detection
    # ══════════════════════════════════════════════════════════════════════
    async def scan_licenses(self) -> list[DetectionResult]:
        """
        Blueprint §6B: flag licenses with inactive users or terminated employees.
        Confidence:
          0.99 — employee terminated (employee_active=False)
          0.75 — no login >60 days
          0.50 — no login >30 days (boundary)
        Only flag if confidence > 0.50.
        """
        from core.config import settings
        from action_handlers.license_handler import get_unused_licenses

        self._start_timer()
        results = []
        licenses = await get_unused_licenses(self.db, settings.UNUSED_LICENSE_DAYS)

        for lic in licenses:
            inactive_days = int(lic.get("inactive_days") or 999)
            employee_active = bool(lic.get("employee_active", True))

            if not employee_active:
                confidence = Confidence.UNUSED_TERMINATED_EMPLOYEE   # 0.99
            elif inactive_days > 60:
                confidence = Confidence.UNUSED_60_DAYS               # 0.75
            elif inactive_days > 30:
                confidence = Confidence.UNUSED_30_DAYS               # 0.50
            else:
                continue

            if confidence <= Confidence.UNUSED_MIN_FLAG:
                continue

            severity = (
                Severity.HIGH if not employee_active
                else Severity.MEDIUM if inactive_days > 60
                else Severity.LOW
            )

            monthly_cost = Decimal(str(lic["monthly_cost"]))

            results.append(DetectionResult(
                agent=self.name,
                model_used=ModelName.QWEN,
                elapsed_ms=self._elapsed_ms(),
                success=True,
                anomaly_type=AnomalyType.UNUSED_SUBSCRIPTION,
                entity_id=lic["id"],
                entity_table="licenses",
                confidence=confidence,
                severity=severity,
                cost_impact_inr=monthly_cost * 12,   # annual impact
                evidence={
                    "license_id": str(lic["id"]),
                    "tool_name": lic["tool_name"],
                    "assigned_email": lic["assigned_email"],
                    "last_login": str(lic.get("last_login")),
                    "inactive_days": inactive_days,
                    "employee_active": employee_active,
                    "monthly_cost": float(monthly_cost),
                    "annual_cost": float(monthly_cost * 12),
                },
            ))

        self.logger.info(
            "scan_licenses: %d licenses → %d flagged (%.0fms)",
            len(licenses), len(results), self._elapsed_ms(),
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # PRICING ANOMALY — >15% above market benchmark
    # ══════════════════════════════════════════════════════════════════════
    async def scan_pricing(self) -> list[DetectionResult]:
        """Blueprint §1: Vendor Pricing Anomaly — invoice rate > benchmark by >15%."""
        from core.config import settings

        self._start_timer()
        results = []

        rows = await self.db.fetch("""
            SELECT
                t.id, t.amount, t.invoice_number, t.vendor_id,
                v.name AS vendor_name,
                v.market_benchmark,
                ((t.amount - v.market_benchmark) / NULLIF(v.market_benchmark, 0)) AS pct_above
            FROM transactions t
            JOIN vendors v ON t.vendor_id = v.id
            WHERE v.market_benchmark IS NOT NULL
              AND v.market_benchmark > 0
              AND t.status IN ('approved', 'pending')
              AND t.amount > v.market_benchmark * $1
        """, 1 + settings.PRICING_ANOMALY_PCT)

        for row in rows:
            pct = float(row["pct_above"] or 0)
            severity = Severity.HIGH if pct > 0.30 else Severity.MEDIUM
            confidence = min(0.95, 0.65 + pct)   # scales with how far above benchmark

            results.append(DetectionResult(
                agent=self.name,
                model_used=ModelName.QWEN,
                elapsed_ms=self._elapsed_ms(),
                success=True,
                anomaly_type=AnomalyType.PRICING_ANOMALY,
                entity_id=row["id"],
                entity_table="transactions",
                confidence=round(confidence, 3),
                severity=severity,
                cost_impact_inr=Decimal(str(row["amount"])) - Decimal(str(row["market_benchmark"])),
                evidence={
                    "transaction_id": str(row["id"]),
                    "invoice_number": row["invoice_number"],
                    "vendor_name": row["vendor_name"],
                    "invoice_amount": float(row["amount"]),
                    "benchmark": float(row["market_benchmark"]),
                    "pct_above_benchmark": round(pct * 100, 1),
                },
            ))

        self.logger.info(
            "scan_pricing: %d anomalies found (%.0fms)",
            len(results), self._elapsed_ms(),
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # RECONCILIATION GAP
    # ══════════════════════════════════════════════════════════════════════
    async def scan_reconciliation(self) -> list[DetectionResult]:
        """
        Blueprint §1: ERP amount vs bank statement delta > ₹500.
        Simplified for demo: flags transactions disputed >48h without resolution.
        """
        self._start_timer()
        results = []

        rows = await self.db.fetch("""
            SELECT t.id, t.amount, t.invoice_number, t.vendor_id,
                   v.name AS vendor_name,
                   EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 3600 AS hours_unresolved
            FROM transactions t
            JOIN vendors v ON t.vendor_id = v.id
            WHERE t.status = 'disputed'
              AND t.created_at < NOW() - INTERVAL '48 hours'
        """)

        for row in rows:
            results.append(DetectionResult(
                agent=self.name,
                model_used=ModelName.QWEN,
                elapsed_ms=self._elapsed_ms(),
                success=True,
                anomaly_type=AnomalyType.RECONCILIATION_GAP,
                entity_id=row["id"],
                entity_table="transactions",
                confidence=0.85,
                severity=Severity.HIGH,
                cost_impact_inr=Decimal(str(row["amount"])),
                evidence={
                    "transaction_id": str(row["id"]),
                    "invoice_number": row["invoice_number"],
                    "vendor_name": row["vendor_name"],
                    "amount": float(row["amount"]),
                    "hours_unresolved": round(float(row["hours_unresolved"]), 1),
                },
            ))

        self.logger.info(
            "scan_reconciliation: %d gaps found (%.0fms)",
            len(results), self._elapsed_ms(),
        )
        return results