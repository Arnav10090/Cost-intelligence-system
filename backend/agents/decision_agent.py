"""
Decision Agent — blueprint §7.

Invokes deepseek-r1:7b for root cause analysis and action recommendation.
Only called for HIGH/CRITICAL severity detections (blueprint §3 UPDATE).
Returns a structured DecisionResult with full reasoning_chain for audit trail.
"""
import json
import logging
from decimal import Decimal
from typing import Optional

import asyncpg

from agents.base_agent import BaseAgent
from agents.interfaces import DecisionResult, DetectionResult
from core.constants import ActionType, AgentName, ModelName, Severity
from models.schemas import AgentTask, DecisionOutput

logger = logging.getLogger(__name__)

# ── Blueprint §7 prompt templates ─────────────────────────────────────────
SYSTEM_PROMPT = """You are a financial risk reasoning agent for an enterprise cost intelligence system.
Analyze the anomaly data precisely and determine the root cause and recommended action.
Output ONLY a valid JSON object. No explanation, markdown, or text outside the JSON.

Required output schema:
{
  "root_cause": "string — specific explanation of why this anomaly occurred",
  "confidence": float between 0.0 and 1.0,
  "action": "one of: hold_payment | license_deactivated | sla_escalation | vendor_renegotiation_flag | email_sent | no_action",
  "action_details": { object with action-specific fields },
  "cost_impact_inr": float — rupee amount at risk or saved,
  "urgency": "one of: LOW | MEDIUM | HIGH | CRITICAL",
  "reasoning_chain": ["Step 1: ...", "Step 2: ...", "Step 3: ..."]
}"""

USER_PROMPT_TEMPLATE = """Anomaly detected:
{anomaly_json}

Historical context:
{context_json}

Analyze this anomaly. Identify the root cause, recommend the most appropriate action,
estimate the financial impact in INR, and provide a step-by-step reasoning chain.
Output ONLY the JSON object described in your instructions."""


class DecisionAgent(BaseAgent):
    def __init__(self, db: asyncpg.Connection):
        super().__init__(AgentName.DECISION, db)

    async def run(self, task: AgentTask) -> DecisionResult:
        """Not used directly — DecisionAgent is called via reason()."""
        return DecisionResult(
            agent=self.name,
            model_used=ModelName.DEEPSEEK,
            elapsed_ms=0,
            success=False,
            error="Use reason() method directly",
        )

    async def reason(
        self,
        detection: DetectionResult,
        extra_context: Optional[dict] = None,
    ) -> DecisionResult:
        """
        Blueprint §7: Invoke deepseek-r1 for root cause analysis.
        Builds context from DB, constructs prompt, parses structured output.
        """
        self._start_timer()

        # ── Build context from DB ──────────────────────────────────────────
        context = await self._build_context(detection)
        if extra_context:
            context.update(extra_context)

        # ── Build prompt ───────────────────────────────────────────────────
        anomaly_json = json.dumps(detection.to_audit_dict(), indent=2, default=str)
        context_json = json.dumps(context, indent=2, default=str)
        prompt = USER_PROMPT_TEMPLATE.format(
            anomaly_json=anomaly_json,
            context_json=context_json,
        )

        # ── Call deepseek-r1 ───────────────────────────────────────────────
        self.logger.info(
            "Invoking deepseek-r1 for %s (severity=%s, entity=%s)",
            detection.anomaly_type,
            detection.severity,
            detection.entity_id,
        )

        try:
            raw_text, model_used = await self._infer(
                prompt,
                severity=detection.severity,
                system_prompt=SYSTEM_PROMPT,
                expect_json=True,
            )
            return self._parse_response(raw_text, model_used, detection)

        except Exception as exc:
            self.logger.error("Decision agent failed: %s", exc)
            return self._fallback_decision(detection, str(exc))

    async def _build_context(self, detection: DetectionResult) -> dict:
        """Fetch relevant historical context from DB for the prompt."""
        context: dict = {}

        if detection.entity_table == "transactions" and detection.entity_id:
            # Vendor history — last 5 transactions
            rows = await self.db.fetch("""
                SELECT t.invoice_number, t.amount, t.transaction_date,
                       t.status, t.po_number
                FROM transactions t
                WHERE t.vendor_id = (
                    SELECT vendor_id FROM transactions WHERE id = $1
                )
                ORDER BY t.transaction_date DESC
                LIMIT 5
            """, detection.entity_id)
            context["vendor_recent_transactions"] = [dict(r) for r in rows]

            # Past anomalies for this vendor
            count = await self.db.fetchval("""
                SELECT COUNT(*) FROM anomaly_logs al
                JOIN transactions t ON al.entity_id = t.id
                WHERE t.vendor_id = (
                    SELECT vendor_id FROM transactions WHERE id = $1
                )
                AND al.anomaly_type = 'duplicate_payment'
            """, detection.entity_id)
            context["vendor_previous_duplicate_count"] = count

        elif detection.entity_table == "sla_metrics" and detection.entity_id:
            row = await self.db.fetchrow(
                "SELECT * FROM sla_metrics WHERE id = $1", detection.entity_id
            )
            if row:
                context["ticket"] = dict(row)

        elif detection.entity_table == "licenses" and detection.entity_id:
            row = await self.db.fetchrow(
                "SELECT * FROM licenses WHERE id = $1", detection.entity_id
            )
            if row:
                context["license"] = dict(row)

        context["evidence"] = detection.evidence
        return context

    def _parse_response(
        self,
        raw_text: str,
        model_used: ModelName,
        detection: DetectionResult,
    ) -> DecisionResult:
        """Parse deepseek-r1 JSON output into DecisionResult."""
        elapsed = self._elapsed_ms()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            self.logger.warning("JSON parse failed: %s — using fallback", e)
            return self._fallback_decision(detection, f"JSON parse error: {e}", model_used)

        # Map action string → ActionType enum
        action_str = data.get("action", "no_action")
        try:
            action_type = ActionType(action_str)
        except ValueError:
            action_type = None

        return DecisionResult(
            agent=self.name,
            model_used=model_used,
            elapsed_ms=elapsed,
            success=True,
            root_cause=data.get("root_cause", ""),
            recommended_action=action_type,
            action_details=data.get("action_details", {}),
            confidence=float(data.get("confidence", detection.confidence)),
            cost_impact_inr=Decimal(str(data.get("cost_impact_inr", detection.cost_impact_inr))),
            urgency=self._parse_severity(data.get("urgency", detection.severity.value if detection.severity else "MEDIUM")),
            reasoning_chain=data.get("reasoning_chain", []),
            raw_llm_output=raw_text,
        )

    def _fallback_decision(
        self,
        detection: DetectionResult,
        error: str,
        model_used: ModelName = ModelName.LLAMA,
    ) -> DecisionResult:
        """
        Deterministic fallback when LLM fails.
        Uses detection evidence to make a safe conservative decision.
        """
        # Map anomaly type to default safe action
        action_map = {
            "duplicate_payment":    ActionType.PAYMENT_HOLD,
            "unused_subscription":  ActionType.LICENSE_DEACTIVATED,
            "sla_risk":             ActionType.SLA_ESCALATION,
            "pricing_anomaly":      ActionType.VENDOR_RENEGOTIATION_FLAG,
            "reconciliation_gap":   ActionType.EMAIL_SENT,
        }
        anomaly_type = detection.anomaly_type.value if detection.anomaly_type else ""
        action = action_map.get(anomaly_type, ActionType.EMAIL_SENT)

        return DecisionResult(
            agent=self.name,
            model_used=model_used,
            elapsed_ms=self._elapsed_ms(),
            success=False,
            error=error,
            root_cause=f"Fallback decision — LLM unavailable. Anomaly type: {anomaly_type}",
            recommended_action=action,
            action_details=detection.evidence,
            confidence=detection.confidence * 0.8,   # reduce confidence for fallback
            cost_impact_inr=detection.cost_impact_inr,
            urgency=detection.severity,
            reasoning_chain=["Step 1: LLM call failed", f"Step 2: Applied default action for {anomaly_type}"],
        )

    @staticmethod
    def _parse_severity(value: str) -> Severity:
        try:
            return Severity(value.upper())
        except ValueError:
            return Severity.MEDIUM