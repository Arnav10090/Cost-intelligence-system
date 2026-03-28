"""
Agent interfaces — standardized input/output contracts.

Every agent method returns one of these dataclasses.
This ensures the Orchestrator can handle any agent's output uniformly,
and the Audit Agent always has a consistent structure to log.

Design principle: dataclasses (not Pydantic) — these are internal pipeline
objects, not HTTP request/response models. Pydantic schemas are in models/.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from core.constants import (
    Severity, AnomalyType, ActionType, ActionState, ModelName, AgentName,
)


# ═══════════════════════════════════════════════════════════════════════════
# BASE
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class AgentResult:
    """Base result — every agent output includes these fields."""
    agent: AgentName
    model_used: Optional[ModelName]
    elapsed_ms: float
    success: bool
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent.value,
            "model_used": self.model_used.value if self.model_used else None,
            "elapsed_ms": self.elapsed_ms,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# DETECTION RESULT  (Anomaly Detection Agent output)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class DetectionResult(AgentResult):
    """
    Returned by AnomalyDetectionAgent for each anomaly found.
    A single scan run may yield multiple DetectionResults.
    """
    anomaly_type: Optional[AnomalyType] = None
    entity_id: Optional[UUID] = None
    entity_table: Optional[str] = None
    confidence: float = 0.0
    severity: Optional[Severity] = None
    cost_impact_inr: Decimal = Decimal("0.00")

    # Raw supporting data passed to the Decision Agent if needed
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def needs_deep_reasoning(self) -> bool:
        """
        Blueprint §3 UPDATE: deepseek-r1 is invoked for ALL HIGH/CRITICAL.
        Confidence threshold kept as secondary guard for rate limiting.
        """
        if self.severity is None:
            return False
        return self.severity.triggers_deepseek

    @property
    def can_auto_action(self) -> bool:
        """Confidence high enough to act without deepseek reasoning."""
        from core.constants import Confidence
        return self.confidence >= Confidence.AUTO_ACTION_MIN

    def to_audit_dict(self) -> dict[str, Any]:
        base = super().to_audit_dict()
        base.update({
            "anomaly_type": self.anomaly_type.value if self.anomaly_type else None,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "entity_table": self.entity_table,
            "confidence": self.confidence,
            "severity": self.severity.value if self.severity else None,
            "cost_impact_inr": float(self.cost_impact_inr),
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════
# DECISION RESULT  (Decision Agent / deepseek-r1 output)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class DecisionResult(AgentResult):
    """
    Returned by DecisionAgent after deepseek-r1 reasoning.
    Includes the full reasoning chain for audit trail visibility.
    """
    root_cause: str = ""
    recommended_action: Optional[ActionType] = None
    action_details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    cost_impact_inr: Decimal = Decimal("0.00")
    urgency: Optional[Severity] = None
    reasoning_chain: list[str] = field(default_factory=list)

    # The raw LLM JSON output (preserved for full auditability)
    raw_llm_output: Optional[str] = None

    def to_audit_dict(self) -> dict[str, Any]:
        base = super().to_audit_dict()
        base.update({
            "root_cause": self.root_cause,
            "recommended_action": self.recommended_action.value if self.recommended_action else None,
            "action_details": self.action_details,
            "confidence": self.confidence,
            "cost_impact_inr": float(self.cost_impact_inr),
            "urgency": self.urgency.value if self.urgency else None,
            "reasoning_chain": self.reasoning_chain,
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════
# ACTION RESULT  (Action Execution Agent output)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class ActionResult(AgentResult):
    """
    Returned by ActionExecutionAgent after performing an action.
    Carries everything needed to write the final audit record.
    """
    action_type: Optional[ActionType] = None
    action_state: ActionState = ActionState.PENDING
    cost_saved: Decimal = Decimal("0.00")
    anomaly_id: Optional[UUID] = None

    # Stored so the action can be rolled back
    rollback_payload: dict[str, Any] = field(default_factory=dict)
    execution_payload: dict[str, Any] = field(default_factory=dict)

    # Set when approval is required (cost > AUTO_APPROVE_LIMIT)
    approval_required: bool = False
    approval_request_id: Optional[UUID] = None

    def to_audit_dict(self) -> dict[str, Any]:
        base = super().to_audit_dict()
        base.update({
            "action_type": self.action_type.value if self.action_type else None,
            "action_state": self.action_state.value,
            "cost_saved": float(self.cost_saved),
            "anomaly_id": str(self.anomaly_id) if self.anomaly_id else None,
            "approval_required": self.approval_required,
        })
        return base


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE RESULT  (full end-to-end trace through the pipeline)
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class PipelineResult:
    """
    Assembled by the Orchestrator after all agents have run.
    This is what gets serialized into the final audit_trail record.
    """
    task_id: str
    task_type: str
    total_elapsed_ms: float

    detections: list[DetectionResult] = field(default_factory=list)
    decisions: list[DecisionResult] = field(default_factory=list)
    actions: list[ActionResult] = field(default_factory=list)

    total_cost_saved: Decimal = Decimal("0.00")
    anomalies_detected: int = 0
    actions_taken: int = 0
    errors: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "total_elapsed_ms": self.total_elapsed_ms,
            "anomalies_detected": self.anomalies_detected,
            "actions_taken": self.actions_taken,
            "total_cost_saved_inr": float(self.total_cost_saved),
            "errors": self.errors,
        }