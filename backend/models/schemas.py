"""
Pydantic v2 schemas for all entities.
Request/Response models for FastAPI + internal agent data structures.
"""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr


# ═══════════════════════════════════════════════════════════════════════════
# VENDOR
# ═══════════════════════════════════════════════════════════════════════════
class VendorBase(BaseModel):
    name: str
    category: str = "Services"
    contract_rate: Optional[Decimal] = None
    payment_terms: int = 30
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    market_benchmark: Optional[Decimal] = None

class VendorCreate(VendorBase):
    pass

class Vendor(VendorBase):
    id: UUID
    created_at: datetime
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# TRANSACTION
# ═══════════════════════════════════════════════════════════════════════════
class TransactionBase(BaseModel):
    vendor_id: Optional[UUID] = None
    invoice_number: str
    amount: Decimal
    currency: str = "INR"
    transaction_date: date
    po_number: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class Transaction(TransactionBase):
    id: UUID
    status: str
    hold_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# LICENSE
# ═══════════════════════════════════════════════════════════════════════════
class LicenseBase(BaseModel):
    tool_name: str
    assigned_email: Optional[str] = None
    monthly_cost: Decimal
    is_active: bool = True
    employee_active: bool = True

class License(LicenseBase):
    id: UUID
    last_login: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
    created_at: datetime
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# SLA METRIC
# ═══════════════════════════════════════════════════════════════════════════
class SLAMetricBase(BaseModel):
    ticket_id: str
    sla_hours: int
    opened_at: datetime
    priority: str = "P2"
    penalty_amount: Decimal = Decimal("0.00")

class SLAMetric(SLAMetricBase):
    id: UUID
    sla_deadline: datetime
    status: str
    breach_prob: float = 0.0
    assignee_id: Optional[UUID] = None
    escalated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# ANOMALY
# ═══════════════════════════════════════════════════════════════════════════
class AnomalyBase(BaseModel):
    anomaly_type: str
    entity_id: Optional[UUID] = None
    entity_table: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    severity: str                              # LOW | MEDIUM | HIGH | CRITICAL
    cost_impact_inr: Decimal = Decimal("0.00")

class AnomalyCreate(AnomalyBase):
    reasoning: Optional[str] = None
    root_cause: Optional[str] = None
    model_used: Optional[str] = None

class Anomaly(AnomalyBase):
    id: UUID
    detected_at: datetime
    reasoning: Optional[str] = None
    root_cause: Optional[str] = None
    model_used: Optional[str] = None
    status: str = "detected"
    override_reason: Optional[str] = None
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# ACTION
# ═══════════════════════════════════════════════════════════════════════════
class ActionCreate(BaseModel):
    anomaly_id: UUID
    action_type: str
    executed_by: str
    cost_saved: Decimal = Decimal("0.00")
    approval_required: bool = False
    payload: dict[str, Any] = {}
    rollback_payload: dict[str, Any] = {}

class Action(ActionCreate):
    id: UUID
    executed_at: datetime
    status: str
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class ActionApproval(BaseModel):
    approved_by: str
    approved: bool
    rejection_reason: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# APPROVAL QUEUE
# ═══════════════════════════════════════════════════════════════════════════
class ApprovalQueueItem(BaseModel):
    id: UUID
    action_id: UUID
    anomaly_id: Optional[UUID] = None
    action_type: str
    cost_impact_inr: Decimal
    requested_by: str
    requested_at: datetime
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    expires_at: Optional[datetime] = None
    payload: Optional[dict[str, Any]] = None
    class Config:
        from_attributes = True


class ApproveRequest(BaseModel):
    approved_by: str


class RejectRequest(BaseModel):
    rejected_by: str
    reason: str


class OverrideRequest(BaseModel):
    """Request to reverse an already-executed action (false positive recovery)."""
    overridden_by: str
    reason: str


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM STATUS (dashboard)
# ═══════════════════════════════════════════════════════════════════════════
class ModelStatus(BaseModel):
    name: str
    loaded: bool
    calls_this_hour: Optional[int] = None
    budget_remaining: Optional[int] = None


class SystemStatus(BaseModel):
    status: str
    env: str
    models: list[ModelStatus]
    deepseek_calls_this_hour: int
    deepseek_budget_remaining: int
    pending_approvals: int


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT TRAIL
# ═══════════════════════════════════════════════════════════════════════════
class AuditRecord(BaseModel):
    audit_id: str
    timestamp: datetime
    agent: str
    model_used: Optional[str]
    input_data: Optional[dict[str, Any]]
    detection: Optional[dict[str, Any]]
    reasoning_invoked: bool = False
    reasoning_model: Optional[str] = None
    reasoning_output: Optional[dict[str, Any]] = None
    action_taken: Optional[dict[str, Any]] = None
    cost_impact_inr: Decimal = Decimal("0.00")
    approval_status: Optional[str] = None
    final_status: str
    override_reason: Optional[str] = None
    class Config:
        from_attributes = True


# ═══════════════════════════════════════════════════════════════════════════
# SAVINGS SUMMARY (dashboard counter)
# ═══════════════════════════════════════════════════════════════════════════
class SavingsSummary(BaseModel):
    duplicate_payments_blocked: Decimal
    unused_subscriptions_cancelled: Decimal
    sla_penalties_avoided: Decimal
    reconciliation_errors_fixed: Decimal
    total_savings_this_month: Decimal
    annual_projection: Decimal
    actions_taken_count: int
    anomalies_detected_count: int
    pending_approvals_count: int


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL AGENT DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════
class AgentTask(BaseModel):
    """Payload pushed to Redis queue by the Orchestrator."""
    task_id: str
    task_type: str      # scan_duplicates | scan_sla | scan_licenses | reconcile
    priority: str = "NORMAL"
    payload: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DecisionOutput(BaseModel):
    """Structured JSON output from deepseek-r1 decision prompt."""
    root_cause: str
    confidence: float
    action: str
    action_details: dict[str, Any] = {}
    cost_impact_inr: float
    urgency: str
    reasoning_chain: list[str] = []