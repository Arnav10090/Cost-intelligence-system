"""
Notification Handler — email dispatch for all alert types.

Blueprint §8: SMTP via Python smtplib (MailHog for demo).
Uses async executor wrapper so SMTP doesn't block the event loop.
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from functools import partial
from typing import Optional

from core.config import settings
from core.constants import AnomalyType, ActionType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════
TEMPLATES: dict[str, dict] = {
    AnomalyType.DUPLICATE_PAYMENT.value: {
        "subject": "[COST ALERT] Duplicate payment detected — ₹{amount}",
        "body": (
            "Cost Intelligence System has detected a potential duplicate payment.\n\n"
            "Details:\n"
            "  Vendor:         {vendor_name}\n"
            "  Invoice:        {invoice_number}\n"
            "  Amount:         ₹{amount}\n"
            "  PO Number:      {po_number}\n"
            "  Confidence:     {confidence:.0%}\n"
            "  Action Taken:   Payment HELD pending review\n\n"
            "Reasoning:\n{reasoning}\n\n"
            "Review at: http://localhost:3000/anomalies/{anomaly_id}\n\n"
            "— Cost Intelligence System"
        ),
    },
    AnomalyType.SLA_RISK.value: {
        "subject": "[SLA ALERT] Breach imminent — {ticket_id} | P(breach)={breach_prob:.0%}",
        "body": (
            "SLA breach risk detected for ticket {ticket_id}.\n\n"
            "Details:\n"
            "  Ticket ID:      {ticket_id}\n"
            "  Priority:       {priority}\n"
            "  SLA Window:     {sla_hours}h\n"
            "  Elapsed:        {elapsed_hours:.1f}h\n"
            "  Breach Prob:    {breach_prob:.0%}\n"
            "  Penalty at Risk: ₹{penalty_amount}\n"
            "  Action Taken:   Ticket escalated\n\n"
            "Review at: http://localhost:3000/sla/{ticket_id}\n\n"
            "— Cost Intelligence System"
        ),
    },
    AnomalyType.UNUSED_SUBSCRIPTION.value: {
        "subject": "[COST ALERT] Unused licenses detected — ₹{monthly_savings}/month",
        "body": (
            "Resource Optimization scan found unused software licenses.\n\n"
            "Summary:\n"
            "  Licenses Deactivated: {count}\n"
            "  Monthly Savings:      ₹{monthly_savings}\n"
            "  Annual Projection:    ₹{annual_savings}\n\n"
            "Breakdown:\n{license_list}\n\n"
            "Review at: http://localhost:3000/licenses\n\n"
            "— Cost Intelligence System"
        ),
    },
    AnomalyType.RECONCILIATION_GAP.value: {
        "subject": "[FINANCE ALERT] Reconciliation gap — ₹{gap_amount} unmatched",
        "body": (
            "Financial reconciliation has identified unmatched transactions.\n\n"
            "Details:\n"
            "  ERP Amount:     ₹{erp_amount}\n"
            "  Bank Amount:    ₹{bank_amount}\n"
            "  Gap:            ₹{gap_amount}\n"
            "  Root Cause:     {root_cause}\n\n"
            "Please review and approve: http://localhost:3000/reconciliation\n\n"
            "— Cost Intelligence System"
        ),
    },
}

DEFAULT_TEMPLATE = {
    "subject": "[COST ALERT] {anomaly_type} detected — severity: {severity}",
    "body": (
        "Cost Intelligence System detected an anomaly.\n\n"
        "Type:      {anomaly_type}\n"
        "Severity:  {severity}\n"
        "Impact:    ₹{cost_impact}\n"
        "Details:   {details}\n\n"
        "Review at: http://localhost:3000\n\n"
        "— Cost Intelligence System"
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# SEND
# ═══════════════════════════════════════════════════════════════════════════
async def send_alert_email(
    to: list[str],
    anomaly_type: str,
    context: dict,
    cc: Optional[list[str]] = None,
) -> bool:
    """
    Send an alert email via MailHog (demo) or real SMTP (production).

    Returns True on success, False on failure (non-raising — email is
    best-effort and should never block the action pipeline).
    """
    template = TEMPLATES.get(anomaly_type, DEFAULT_TEMPLATE)

    try:
        subject = template["subject"].format(**context)
        body = template["body"].format(**context)
    except KeyError as e:
        logger.warning("Email template missing key %s for %s — using fallback", e, anomaly_type)
        subject = f"[COST ALERT] {anomaly_type}"
        body = f"Anomaly detected: {context}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(body)

    # Run blocking SMTP call in thread pool — don't block the event loop
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, partial(_smtp_send, msg))
        logger.info("Email sent → %s | subject: %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False


def _smtp_send(msg: EmailMessage) -> None:
    """Blocking SMTP send — runs in thread pool executor."""
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        smtp.send_message(msg)


# ═══════════════════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPERS
# ═══════════════════════════════════════════════════════════════════════════
async def notify_duplicate_payment(
    vendor_name: str,
    invoice_number: str,
    amount: float,
    po_number: str,
    confidence: float,
    reasoning: str,
    anomaly_id: str,
) -> bool:
    return await send_alert_email(
        to=[settings.ALERT_EMAIL],
        anomaly_type=AnomalyType.DUPLICATE_PAYMENT.value,
        context={
            "vendor_name": vendor_name,
            "invoice_number": invoice_number,
            "amount": f"{amount:,.0f}",
            "po_number": po_number,
            "confidence": confidence,
            "reasoning": reasoning,
            "anomaly_id": anomaly_id,
        },
    )


async def notify_sla_escalation(
    ticket_id: str,
    priority: str,
    sla_hours: int,
    elapsed_hours: float,
    breach_prob: float,
    penalty_amount: float,
) -> bool:
    return await send_alert_email(
        to=[settings.ALERT_EMAIL],
        anomaly_type=AnomalyType.SLA_RISK.value,
        context={
            "ticket_id": ticket_id,
            "priority": priority,
            "sla_hours": sla_hours,
            "elapsed_hours": elapsed_hours,
            "breach_prob": breach_prob,
            "penalty_amount": f"{penalty_amount:,.0f}",
        },
    )