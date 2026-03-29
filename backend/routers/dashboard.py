"""
Dashboard router — aggregated endpoint for optimized dashboard loading.
Part of API Call Optimization feature to reduce API calls by 70-80%.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from models.schemas import SavingsSummary, Anomaly, Action, SystemStatus


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD AGGREGATED SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class DashboardSummary(BaseModel):
    """
    Aggregated dashboard data returned in a single response.
    Combines savings, recent anomalies, recent actions, pending approvals count,
    and system status to reduce API calls from 6 to 1 on initial load.
    
    Requirements: 3.1, 3.2
    """
    savings: SavingsSummary
    recent_anomalies: list[Anomaly]  # limit 10
    recent_actions: list[Action]  # limit 10
    pending_approvals_count: int
    system_status: SystemStatus
    timestamp: datetime
    
    class Config:
        from_attributes = True


class DashboardSummaryResponse(BaseModel):
    """
    Response wrapper for aggregated dashboard endpoint.
    Supports partial data return when some components fail (graceful degradation).
    
    Requirements: 3.4
    """
    data: Optional[DashboardSummary] = None
    errors: dict[str, str] = {}  # component -> error message
    partial: bool = False  # True if any component failed
    
    class Config:
        from_attributes = True


import asyncio
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends

from db.database import get_db
from services.cost_calculator import get_savings_summary
from core.constants import ActionState
from core.config import settings


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ═══════════════════════════════════════════════════════════════════════════
# AGGREGATED ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(db: asyncpg.Connection = Depends(get_db)):
    """
    Aggregated dashboard endpoint that returns all dashboard data in a single request.
    
    Queries in parallel:
    - Savings summary
    - Recent anomalies (limit 10)
    - Recent actions (limit 10)
    - Pending approvals count
    - System status
    
    Uses asyncio.gather() with return_exceptions=True for graceful degradation.
    If any component fails, returns partial data with error indicators.
    
    Requirements: 3.2, 3.3, 3.4, 8.1
    Target: <200ms p95 latency
    """
    import time
    start_time = time.time()
    
    # Define async functions for each component
    async def fetch_savings() -> SavingsSummary:
        """Fetch savings summary."""
        return await get_savings_summary(db)
    
    async def fetch_recent_anomalies() -> list[dict[str, Any]]:
        """Fetch recent 10 anomalies."""
        rows = await db.fetch("""
            SELECT al.*,
                   COALESCE(at2.action_type, NULL) AS latest_action,
                   COALESCE(at2.status, NULL)       AS action_status
            FROM anomaly_logs al
            LEFT JOIN LATERAL (
                SELECT action_type, status FROM actions_taken
                WHERE anomaly_id = al.id ORDER BY executed_at DESC LIMIT 1
            ) at2 ON TRUE
            ORDER BY al.detected_at DESC
            LIMIT 10
        """)
        return [dict(r) for r in rows]
    
    async def fetch_recent_actions() -> list[dict[str, Any]]:
        """Fetch recent 10 actions."""
        rows = await db.fetch("""
            SELECT a.*, al.anomaly_type, al.severity, al.confidence, al.model_used
            FROM actions_taken a
            LEFT JOIN anomaly_logs al ON a.anomaly_id = al.id
            ORDER BY a.executed_at DESC
            LIMIT 10
        """)
        return [dict(r) for r in rows]
    
    async def fetch_pending_approvals_count() -> int:
        """Fetch count of pending approvals."""
        count = await db.fetchval(
            "SELECT COUNT(*) FROM actions_taken WHERE status = $1",
            ActionState.PENDING_APPROVAL.value
        )
        return count or 0
    
    async def fetch_system_status() -> dict[str, Any]:
        """Fetch system status."""
        # Get pending approvals count (already fetched above, but needed for system status)
        pending = await db.fetchval(
            "SELECT COUNT(*) FROM actions_taken WHERE status = 'pending_approval'"
        )
        
        # LLM router state
        try:
            from services.llm_router import (
                deepseek_calls_this_hour,
                deepseek_budget_remaining,
                get_loaded_models,
            )
            from core.constants import ModelName
            
            calls = deepseek_calls_this_hour()
            budget = deepseek_budget_remaining()
            loaded_models = await get_loaded_models()
            loaded_names = {m.get("name", "") for m in loaded_models}
            
            models = [
                {
                    "name": ModelName.QWEN.value,
                    "status": "loaded" if ModelName.QWEN.value in loaded_names else "unloaded",
                    "type": "local",
                },
                {
                    "name": ModelName.DEEPSEEK.value,
                    "status": "available" if budget > 0 else "quota_exceeded",
                    "type": "api",
                    "calls_this_hour": calls,
                    "budget_remaining": budget,
                },
            ]
        except Exception:
            # Fallback if LLM router is unavailable
            calls = 0
            budget = getattr(settings, 'MAX_DEEPSEEK_CALLS_PER_HOUR', 100)
            models = [
                {"name": "qwen2.5:32b", "status": "unknown", "type": "local"},
                {"name": "deepseek-chat", "status": "unknown", "type": "api"},
            ]
        
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "models": models,
            "deepseek_calls_this_hour": calls,
            "deepseek_budget_remaining": budget,
            "pending_approvals": pending or 0,
        }
    
    # Execute all queries in parallel with exception handling
    results = await asyncio.gather(
        fetch_savings(),
        fetch_recent_anomalies(),
        fetch_recent_actions(),
        fetch_pending_approvals_count(),
        fetch_system_status(),
        return_exceptions=True
    )
    
    # Unpack results and track errors
    errors: dict[str, str] = {}
    partial = False
    
    # Process savings
    if isinstance(results[0], Exception):
        errors["savings"] = str(results[0])
        partial = True
        savings = None
    else:
        savings = results[0]
    
    # Process recent anomalies
    if isinstance(results[1], Exception):
        errors["recent_anomalies"] = str(results[1])
        partial = True
        recent_anomalies = []
    else:
        recent_anomalies = results[1]
    
    # Process recent actions
    if isinstance(results[2], Exception):
        errors["recent_actions"] = str(results[2])
        partial = True
        recent_actions = []
    else:
        recent_actions = results[2]
    
    # Process pending approvals count
    if isinstance(results[3], Exception):
        errors["pending_approvals_count"] = str(results[3])
        partial = True
        pending_approvals_count = 0
    else:
        pending_approvals_count = results[3]
    
    # Process system status
    if isinstance(results[4], Exception):
        errors["system_status"] = str(results[4])
        partial = True
        system_status = None
    else:
        system_status = results[4]
    
    # If all components failed, return error response
    if len(errors) == 5:
        return DashboardSummaryResponse(
            data=None,
            errors=errors,
            partial=True
        )
    
    # Build dashboard summary with available data
    # Use default values for failed components
    if savings is None:
        from decimal import Decimal
        savings = SavingsSummary(
            duplicate_payments_blocked=Decimal("0.00"),
            unused_subscriptions_cancelled=Decimal("0.00"),
            sla_penalties_avoided=Decimal("0.00"),
            reconciliation_errors_fixed=Decimal("0.00"),
            total_savings_this_month=Decimal("0.00"),
            annual_projection=Decimal("0.00"),
            actions_taken_count=0,
            anomalies_detected_count=0,
            pending_approvals_count=0
        )
    
    if system_status is None:
        system_status = {
            "status": "unknown",
            "env": settings.APP_ENV,
            "models": [],
            "deepseek_calls_this_hour": 0,
            "deepseek_budget_remaining": 0,
            "pending_approvals": pending_approvals_count,
        }
    
    dashboard_data = DashboardSummary(
        savings=savings,
        recent_anomalies=recent_anomalies,
        recent_actions=recent_actions,
        pending_approvals_count=pending_approvals_count,
        system_status=system_status,
        timestamp=datetime.utcnow()
    )
    
    # Record latency for monitoring (Requirements 8.1)
    latency_ms = (time.time() - start_time) * 1000
    try:
        from services.metrics_collector import get_metrics_collector
        metrics_collector = get_metrics_collector()
        metrics_collector.record_aggregated_endpoint_latency(latency_ms)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("Failed to record latency: %s", e)
    
    return DashboardSummaryResponse(
        data=dashboard_data,
        errors=errors,
        partial=partial
    )
