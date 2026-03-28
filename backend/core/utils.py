"""
Shared utility functions.
Pure functions only — no DB or network calls here.
"""
import math
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from core.constants import CURRENCY_SYMBOL


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT ID GENERATION
# ═══════════════════════════════════════════════════════════════════════════
_audit_counter: dict[str, int] = {}


def generate_audit_id() -> str:
    """
    Generate a human-readable audit ID: aud-YYYYMMDD-NNN
    e.g. aud-20240115-001
    Thread-safe within a single process (APScheduler + FastAPI workers).
    """
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    _audit_counter[today] = _audit_counter.get(today, 0) + 1
    return f"aud-{today}-{_audit_counter[today]:03d}"


# ═══════════════════════════════════════════════════════════════════════════
# MATH HELPERS  (used by detection algorithms)
# ═══════════════════════════════════════════════════════════════════════════
def sigmoid(x: float) -> float:
    """
    Standard logistic sigmoid.
    Used in SLA breach probability: sigmoid(10 * (progress_ratio - 0.75))
    """
    return 1.0 / (1.0 + math.exp(-x))


def sla_breach_probability(
    elapsed_hours: float,
    sla_hours: int,
    has_assignee: bool = True,
    priority: str = "P2",
    status: str = "open",
) -> float:
    """
    Blueprint §6C formula — returns P(breach) in [0.0, 1.0].

    Modifiers:
      - No assignee   → ×1.4
      - P1 priority   → ×1.3
      - Open >80% SLA → ×1.2
    """
    progress = elapsed_hours / max(sla_hours, 1)
    p = sigmoid(10 * (progress - 0.75))

    if not has_assignee:
        p *= 1.4
    if priority == "P1":
        p *= 1.3
    if status == "open" and progress > 0.8:
        p *= 1.2

    return min(p, 1.0)


# ═══════════════════════════════════════════════════════════════════════════
# STRING HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def levenshtein(s1: str, s2: str) -> int:
    """
    Classic edit-distance — used for fuzzy invoice number matching
    (blueprint §6A: levenshtein(c.invoice_number, txn.invoice_number) <= 2).
    """
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def normalize_invoice(invoice: str) -> str:
    """Strip non-alphanumeric for comparison (handles INV-001 vs INV001)."""
    return re.sub(r"[^A-Z0-9]", "", invoice.upper())


def fingerprint_transaction(vendor_id: str, amount: float, po_number: str) -> str:
    """
    Short hash for fast duplicate pre-filter before detailed DB query.
    Same vendor + rounded amount + same PO → identical fingerprint.
    """
    key = f"{vendor_id}|{round(amount, -2)}|{po_number or ''}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════
# CURRENCY FORMATTING
# ═══════════════════════════════════════════════════════════════════════════
def format_inr(amount: float | Decimal) -> str:
    """Format a rupee amount with Indian number system (lakhs/crores)."""
    val = float(amount)
    if val >= 1_00_00_000:
        return f"{CURRENCY_SYMBOL}{val / 1_00_00_000:.2f} Cr"
    if val >= 1_00_000:
        return f"{CURRENCY_SYMBOL}{val / 1_00_000:.2f} L"
    if val >= 1_000:
        return f"{CURRENCY_SYMBOL}{val / 1_000:.1f}K"
    return f"{CURRENCY_SYMBOL}{val:,.0f}"


def annual_projection(monthly_savings: float) -> float:
    """Blueprint §9 Formula 4."""
    return monthly_savings * 12


# ═══════════════════════════════════════════════════════════════════════════
# TIMESTAMP HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hours_elapsed(since: datetime) -> float:
    now = datetime.now(timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return (now - since).total_seconds() / 3600


def days_elapsed(since: datetime) -> int:
    return int(hours_elapsed(since) / 24)


# ═══════════════════════════════════════════════════════════════════════════
# JSON SERIALIZATION HELPER
# ═══════════════════════════════════════════════════════════════════════════
def safe_jsonable(obj: Any) -> Any:
    """
    Recursively convert non-JSON-serializable types for asyncpg JSONB columns.
    Handles: Decimal, datetime, UUID, Enum.
    """
    import uuid
    from enum import Enum

    if isinstance(obj, dict):
        return {k: safe_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [safe_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    return obj