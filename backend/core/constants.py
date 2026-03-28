"""
System-wide constants and enumerations.
Use these instead of raw strings everywhere — prevents typos and
gives IDE completion across agents, routers, and handlers.
"""
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════
# SEVERITY LEVELS
# ═══════════════════════════════════════════════════════════════════════════
class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def triggers_deepseek(self) -> bool:
        """Blueprint §3: deepseek-r1 is invoked for ALL HIGH and CRITICAL."""
        return self in (Severity.HIGH, Severity.CRITICAL)

    @property
    def weight(self) -> int:
        """Numeric weight for comparisons and sorting."""
        return {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}[self.value]

    def __gt__(self, other: "Severity") -> bool:
        return self.weight > other.weight

    def __lt__(self, other: "Severity") -> bool:
        return self.weight < other.weight


# ═══════════════════════════════════════════════════════════════════════════
# ANOMALY TYPES
# ═══════════════════════════════════════════════════════════════════════════
class AnomalyType(str, Enum):
    DUPLICATE_PAYMENT = "duplicate_payment"
    UNUSED_SUBSCRIPTION = "unused_subscription"
    SLA_RISK = "sla_risk"
    RECONCILIATION_GAP = "reconciliation_gap"
    PRICING_ANOMALY = "pricing_anomaly"
    INFRA_WASTE = "infra_waste"


# ═══════════════════════════════════════════════════════════════════════════
# ACTION TYPES
# ═══════════════════════════════════════════════════════════════════════════
class ActionType(str, Enum):
    PAYMENT_HOLD = "payment_hold"
    PAYMENT_RELEASE = "payment_release"
    EMAIL_SENT = "email_sent"
    LICENSE_DEACTIVATED = "license_deactivated"
    LICENSE_RESTORED = "license_restored"
    SLA_ESCALATION = "sla_escalation"
    VENDOR_RENEGOTIATION_FLAG = "vendor_renegotiation_flag"
    RESOURCE_DOWNSIZE = "resource_downsize"
    RESOURCE_RESTORED = "resource_restored"


# ═══════════════════════════════════════════════════════════════════════════
# ACTION STATES  (full lifecycle incl. approval and override flows)
# ═══════════════════════════════════════════════════════════════════════════
class ActionState(str, Enum):
    # Normal execution path
    PENDING = "pending"                       # queued, not yet executed
    SUCCESS = "success"                       # executed, confirmed
    FAILED = "failed"                         # execution error

    # Approval workflow (cost_impact > AUTO_APPROVE_LIMIT)
    PENDING_APPROVAL = "pending_approval"     # awaiting human approval
    APPROVED = "approved"                     # approved, will be executed
    REJECTED = "rejected"                     # human rejected — action not taken

    # Override / rollback
    ROLLED_BACK = "rolled_back"               # action was reversed post-execution
    OVERRIDDEN = "overridden"                 # flagged as false-positive, reversed

    @property
    def is_terminal(self) -> bool:
        return self in (
            ActionState.SUCCESS, ActionState.FAILED,
            ActionState.REJECTED, ActionState.ROLLED_BACK,
            ActionState.OVERRIDDEN,
        )

    @property
    def is_reversible(self) -> bool:
        """Actions that can be rolled back by a human override."""
        return self in (ActionState.SUCCESS, ActionState.APPROVED)


# ═══════════════════════════════════════════════════════════════════════════
# ANOMALY STATUS (lifecycle in anomaly_logs)
# ═══════════════════════════════════════════════════════════════════════════
class AnomalyStatus(str, Enum):
    DETECTED = "detected"
    ACTIONED = "actioned"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    OVERRIDDEN = "overridden"


# ═══════════════════════════════════════════════════════════════════════════
# MODEL NAMES
# ═══════════════════════════════════════════════════════════════════════════
class ModelName(str, Enum):
    QWEN = "qwen2.5:7b"
    DEEPSEEK = "deepseek-r1:7b"
    LLAMA = "llama3.2:3b"


# ═══════════════════════════════════════════════════════════════════════════
# AGENT NAMES
# ═══════════════════════════════════════════════════════════════════════════
class AgentName(str, Enum):
    ORCHESTRATOR = "OrchestratorAgent"
    ANOMALY = "AnomalyDetectionAgent"
    DECISION = "DecisionAgent"
    ACTION = "ActionExecutionAgent"
    AUDIT = "AuditAgent"
    FALLBACK = "FallbackAgent"


# ═══════════════════════════════════════════════════════════════════════════
# TASK TYPES (Redis queue)
# ═══════════════════════════════════════════════════════════════════════════
class TaskType(str, Enum):
    SCAN_DUPLICATES = "scan_duplicates"
    SCAN_SLA = "scan_sla"
    SCAN_LICENSES = "scan_licenses"
    RECONCILE = "reconcile"
    SCAN_PRICING = "scan_pricing"
    SCAN_INFRA = "scan_infra"
    DEMO_TRIGGER = "demo_trigger"


# ═══════════════════════════════════════════════════════════════════════════
# CONFIDENCE THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════
class Confidence:
    DUPLICATE_SAME_PO: float = 0.97
    DUPLICATE_SIMILAR_INVOICE: float = 0.82
    DUPLICATE_AMOUNT_VENDOR: float = 0.65
    DUPLICATE_MIN_FLAG: float = 0.60

    UNUSED_TERMINATED_EMPLOYEE: float = 0.99
    UNUSED_60_DAYS: float = 0.75
    UNUSED_30_DAYS: float = 0.50
    UNUSED_MIN_FLAG: float = 0.50

    AUTO_ACTION_MIN: float = 0.85       # confidence > 0.85 → auto-execute action


# ═══════════════════════════════════════════════════════════════════════════
# REDIS QUEUE NAMES
# ═══════════════════════════════════════════════════════════════════════════
class RedisQueue(str, Enum):
    TASKS = "ci:tasks"
    RESULTS = "ci:results"
    ALERTS = "ci:alerts"
    PREWARM = "ci:prewarm"


# ═══════════════════════════════════════════════════════════════════════════
# CURRENCY
# ═══════════════════════════════════════════════════════════════════════════
CURRENCY_SYMBOL = "₹"
DEFAULT_CURRENCY = "INR"