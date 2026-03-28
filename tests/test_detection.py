"""
Tests for detection algorithm logic.

Covers:
  - Duplicate payment detection (confidence tiers, PO match, fuzzy invoice)
  - SLA breach probability formula (all modifier branches)
  - Unused subscription detection (terminated vs inactive)
  - Edge cases (boundary conditions, empty sets)
"""
import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from core.constants import Confidence
from core.utils import (
    sla_breach_probability,
    levenshtein,
    normalize_invoice,
    fingerprint_transaction,
)


# ═══════════════════════════════════════════════════════════════════════════
# LEVENSHTEIN
# ═══════════════════════════════════════════════════════════════════════════
class TestLevenshtein:
    def test_identical_strings(self):
        assert levenshtein("INV-2891A", "INV-2891A") == 0

    def test_one_char_diff(self):
        assert levenshtein("INV-2891A", "INV-2891B") == 1

    def test_two_char_diff(self):
        assert levenshtein("INV-001", "INV-003") == 1   # '1' → '3'

    def test_empty_string(self):
        assert levenshtein("", "ABC") == 3
        assert levenshtein("ABC", "") == 3

    def test_completely_different(self):
        assert levenshtein("ABC", "XYZ") == 3

    def test_blueprint_threshold(self):
        """Blueprint §6A: flag when levenshtein(invoice_a, invoice_b) <= 2."""
        assert levenshtein("INV-2891A", "INV-2891B") <= 2   # should flag
        assert levenshtein("INV-2891A", "INV-9999Z") > 2    # should not flag


class TestNormalizeInvoice:
    def test_strips_hyphens(self):
        assert normalize_invoice("INV-001") == "INV001"

    def test_case_insensitive(self):
        assert normalize_invoice("inv-001") == "INV001"

    def test_already_clean(self):
        assert normalize_invoice("INV001") == "INV001"


# ═══════════════════════════════════════════════════════════════════════════
# FINGERPRINT
# ═══════════════════════════════════════════════════════════════════════════
class TestFingerprint:
    def test_same_inputs_same_hash(self):
        vid = "vendor-abc"
        f1 = fingerprint_transaction(vid, 45000.0, "PO-2891")
        f2 = fingerprint_transaction(vid, 45000.0, "PO-2891")
        assert f1 == f2

    def test_different_vendor_different_hash(self):
        f1 = fingerprint_transaction("vendor-abc", 45000.0, "PO-2891")
        f2 = fingerprint_transaction("vendor-xyz", 45000.0, "PO-2891")
        assert f1 != f2

    def test_amount_rounding(self):
        """Small amount differences (within 2%) should hash the same bucket."""
        # Both round to 45000 (nearest 100)
        f1 = fingerprint_transaction("v1", 44950.0, "PO-1")
        f2 = fingerprint_transaction("v1", 45049.0, "PO-1")
        assert f1 == f2

    def test_output_is_12_chars(self):
        f = fingerprint_transaction("v1", 10000.0, "PO-1")
        assert len(f) == 12


# ═══════════════════════════════════════════════════════════════════════════
# SLA BREACH PROBABILITY  (blueprint §6C)
# ═══════════════════════════════════════════════════════════════════════════
class TestSLABreachProbability:
    def test_early_progress_low_probability(self):
        """At 10% of SLA window, breach probability should be very low."""
        p = sla_breach_probability(elapsed_hours=0.4, sla_hours=4)
        assert p < 0.05

    def test_at_75_percent_inflection(self):
        """Sigmoid inflection at 75% — probability near 0.5."""
        p = sla_breach_probability(elapsed_hours=3.0, sla_hours=4)
        assert 0.4 < p < 0.6

    def test_at_82_percent_triggers_escalation(self):
        """Blueprint §6C: near-breach tickets at 82% should exceed 0.70 threshold."""
        p = sla_breach_probability(
            elapsed_hours=3.28,   # 82% of 4h SLA
            sla_hours=4,
            has_assignee=False,   # no assignee — ×1.4 modifier
            priority="P1",        # P1 — ×1.3 modifier
            status="open",
        )
        assert p >= 0.70, f"Expected >= 0.70 but got {p:.3f}"

    def test_no_assignee_modifier(self):
        """No assignee multiplies probability by 1.4."""
        p_with = sla_breach_probability(3.2, 4, has_assignee=True)
        p_without = sla_breach_probability(3.2, 4, has_assignee=False)
        assert p_without > p_with

    def test_p1_modifier(self):
        """P1 priority multiplies probability by 1.3."""
        p_p1 = sla_breach_probability(3.2, 4, priority="P1")
        p_p2 = sla_breach_probability(3.2, 4, priority="P2")
        assert p_p1 > p_p2

    def test_probability_capped_at_one(self):
        """P(breach) must never exceed 1.0."""
        p = sla_breach_probability(
            elapsed_hours=10.0,
            sla_hours=4,
            has_assignee=False,
            priority="P1",
            status="open",
        )
        assert p <= 1.0

    def test_breach_escalation_threshold(self):
        """Blueprint: trigger action at P(breach) >= 0.70."""
        from core.config import settings
        p = sla_breach_probability(
            elapsed_hours=3.5,
            sla_hours=4,
            has_assignee=False,
            priority="P1",
            status="open",
        )
        should_escalate = p >= settings.SLA_ESCALATION_THRESHOLD
        assert should_escalate, f"P={p:.3f} did not meet escalation threshold"

    def test_resolved_ticket_edge_case(self):
        """Expired SLA window — progress ratio > 1.0, result still in [0,1]."""
        p = sla_breach_probability(elapsed_hours=8.0, sla_hours=4)
        assert 0.0 <= p <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# DUPLICATE CONFIDENCE TIERS  (blueprint §6A)
# ═══════════════════════════════════════════════════════════════════════════
class TestDuplicateConfidenceTiers:
    """Verify confidence constants match blueprint §6A thresholds."""

    def test_same_po_confidence(self):
        assert Confidence.DUPLICATE_SAME_PO == 0.97

    def test_similar_invoice_confidence(self):
        assert Confidence.DUPLICATE_SIMILAR_INVOICE == 0.82

    def test_amount_vendor_only_confidence(self):
        assert Confidence.DUPLICATE_AMOUNT_VENDOR == 0.65

    def test_minimum_flag_threshold(self):
        """Only flag when confidence > 0.60."""
        assert Confidence.DUPLICATE_MIN_FLAG == 0.60

    def test_same_po_above_auto_action_threshold(self):
        """Same PO confidence (0.97) exceeds auto-action threshold (0.85)."""
        assert Confidence.DUPLICATE_SAME_PO > Confidence.AUTO_ACTION_MIN

    def test_amount_vendor_below_auto_action_threshold(self):
        """Amount+vendor match only (0.65) should NOT auto-action — needs approval."""
        assert Confidence.DUPLICATE_AMOUNT_VENDOR < Confidence.AUTO_ACTION_MIN


# ═══════════════════════════════════════════════════════════════════════════
# UNUSED SUBSCRIPTION CONFIDENCE  (blueprint §6B)
# ═══════════════════════════════════════════════════════════════════════════
class TestUnusedSubscriptionConfidence:
    def test_terminated_employee_confidence(self):
        """Terminated employee + active license = 0.99 confidence."""
        assert Confidence.UNUSED_TERMINATED_EMPLOYEE == 0.99

    def test_terminated_employee_above_auto_action(self):
        """0.99 > AUTO_ACTION_MIN (0.85) → auto-deactivate without approval."""
        assert Confidence.UNUSED_TERMINATED_EMPLOYEE > Confidence.AUTO_ACTION_MIN

    def test_60_day_inactive_confidence(self):
        assert Confidence.UNUSED_60_DAYS == 0.75

    def test_30_day_inactive_confidence(self):
        assert Confidence.UNUSED_30_DAYS == 0.50

    def test_30_day_inactive_at_boundary(self):
        """30-day confidence is exactly at the minimum flag threshold."""
        assert Confidence.UNUSED_30_DAYS == Confidence.UNUSED_MIN_FLAG


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE-BACKED DETECTION QUERIES  (integration tests using seed_db)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestDuplicateDetectionDB:
    async def test_finds_duplicate_same_po(self, db, seed_db):
        """The seed data contains one duplicate pair on PO-TEST-001."""
        rows = await db.fetch("""
            SELECT t1.id AS original_id, t2.id AS duplicate_id,
                   t1.amount, t1.po_number
            FROM transactions t1
            JOIN transactions t2 ON (
                t1.vendor_id = t2.vendor_id
                AND t1.po_number = t2.po_number
                AND ABS(t1.amount - t2.amount) / t1.amount < 0.02
                AND t1.id != t2.id
                AND t2.transaction_date BETWEEN
                    t1.transaction_date - INTERVAL '30 days' AND t1.transaction_date + INTERVAL '30 days'
            )
            WHERE t1.status = 'approved'
              AND t2.status = 'pending'
        """)
        assert len(rows) >= 1, "Expected at least one duplicate pair in seed data"
        assert rows[0]["po_number"] == "PO-TEST-001"

    async def test_duplicate_amounts_match(self, db, seed_db):
        """Both invoices in the duplicate pair have identical amounts."""
        rows = await db.fetch("""
            SELECT amount FROM transactions WHERE po_number = 'PO-TEST-001'
        """)
        amounts = [r["amount"] for r in rows]
        assert len(amounts) == 2
        assert amounts[0] == amounts[1]


@pytest.mark.asyncio
class TestUnusedLicenseDB:
    async def test_finds_terminated_employee_license(self, db, seed_db):
        """Terminated employee license should be in the unused set."""
        rows = await db.fetch("""
            SELECT id, tool_name, employee_active, last_login
            FROM licenses
            WHERE is_active = TRUE AND employee_active = FALSE
        """)
        assert len(rows) >= 1
        assert rows[0]["tool_name"] == "Slack"

    async def test_finds_60_day_inactive_license(self, db, seed_db):
        """65-day inactive license should be in the unused set."""
        rows = await db.fetch("""
            SELECT id, tool_name,
                   EXTRACT(DAY FROM NOW() - last_login)::INT AS inactive_days
            FROM licenses
            WHERE is_active = TRUE
              AND employee_active = TRUE
              AND last_login < NOW() - INTERVAL '60 days'
        """)
        assert len(rows) >= 1
        assert any(r["inactive_days"] >= 60 for r in rows)

    async def test_active_recent_license_not_flagged(self, db, seed_db):
        """A license used yesterday should not be in the unused set."""
        recent_id = await db.fetchval("""
            INSERT INTO licenses
                (id, tool_name, assigned_email, last_login, is_active, monthly_cost, employee_active)
            VALUES (gen_random_uuid(), 'GitHub', 'active@company.local',
                    NOW() - INTERVAL '1 day', TRUE, 1000.00, TRUE)
            RETURNING id
        """)
        row = await db.fetchrow("""
            SELECT id FROM licenses
            WHERE id = $1
              AND last_login < NOW() - INTERVAL '60 days'
        """, recent_id)
        assert row is None, "Recently-active license should NOT be flagged"