"""
Event Broadcaster — Centralized event publishing for real-time WebSocket updates.

This module provides type-safe event publishing methods that broadcast domain events
to Redis pub/sub channels. WebSocket clients subscribe to these channels to receive
real-time updates when data changes.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from services.redis_client import EventChannel, publish_event

logger = logging.getLogger(__name__)

# Import invalidate_etag for cache invalidation
# Lazy import to avoid circular dependency
_invalidate_etag = None


def _get_invalidate_etag():
    """Lazy import of invalidate_etag to avoid circular dependency."""
    global _invalidate_etag
    if _invalidate_etag is None:
        from middleware.etag_middleware import invalidate_etag
        _invalidate_etag = invalidate_etag
    return _invalidate_etag


class EventBroadcaster:
    """
    Publishes domain events to Redis pub/sub for WebSocket broadcasting.
    
    This class provides type-safe methods for publishing events when data changes
    in the Cost Intelligence System. Each method corresponds to a specific event
    type and ensures proper message structure.
    
    Requirements: 7.1
    """
    
    @staticmethod
    async def publish_anomaly_created(anomaly: dict[str, Any]) -> None:
        """
        Publish when a new anomaly is detected.
        
        Args:
            anomaly: Complete Anomaly object as dict (must include id, anomaly_type,
                    detected_at, confidence, severity, cost_impact_inr, etc.)
        
        Requirements: 7.2, 2.7
        
        Example:
            await EventBroadcaster.publish_anomaly_created({
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "anomaly_type": "duplicate_payment",
                "detected_at": "2024-01-15T10:30:00Z",
                "confidence": 0.95,
                "severity": "HIGH",
                "cost_impact_inr": 5000.00,
                ...
            })
        """
        event_data = {
            "type": "anomaly_created",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "anomaly": EventBroadcaster._serialize_event_data(anomaly)
            }
        }
        await publish_event(EventChannel.ANOMALY_CREATED, event_data)
        
        # Invalidate ETags for anomaly-related endpoints
        # Requirements: 2.7 (Backend SHALL invalidate ETags within 2 seconds when underlying data changes)
        invalidate_etag = _get_invalidate_etag()
        await invalidate_etag("/api/anomalies/")
        await invalidate_etag("/api/dashboard/summary")
        
        logger.info(
            "Event published: anomaly_created (id=%s, type=%s)",
            anomaly.get("id"),
            anomaly.get("anomaly_type")
        )
    
    @staticmethod
    async def publish_action_executed(
        action: dict[str, Any],
        anomaly_id: UUID | str | None = None
    ) -> None:
        """
        Publish when an action is executed.
        
        Args:
            action: Complete Action object as dict (must include id, action_type,
                   executed_at, status, cost_saved, etc.)
            anomaly_id: Optional UUID of the related anomaly
        
        Requirements: 7.3, 2.7
        
        Example:
            await EventBroadcaster.publish_action_executed({
                "id": "456e7890-e89b-12d3-a456-426614174000",
                "action_type": "cancel_subscription",
                "executed_at": "2024-01-15T10:35:00Z",
                "status": "completed",
                "cost_saved": 5000.00,
                ...
            }, anomaly_id="123e4567-e89b-12d3-a456-426614174000")
        """
        event_data = {
            "type": "action_executed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "action": EventBroadcaster._serialize_event_data(action),
                "anomaly_id": str(anomaly_id) if anomaly_id else None
            }
        }
        await publish_event(EventChannel.ACTION_EXECUTED, event_data)
        
        # Invalidate ETags for action-related endpoints
        # Requirements: 2.7
        invalidate_etag = _get_invalidate_etag()
        await invalidate_etag("/api/actions/")
        await invalidate_etag("/api/dashboard/summary")
        
        logger.info(
            "Event published: action_executed (id=%s, type=%s)",
            action.get("id"),
            action.get("action_type")
        )
    
    @staticmethod
    async def publish_approval_status_changed(approval: dict[str, Any]) -> None:
        """
        Publish when an approval status changes.
        
        Args:
            approval: Complete ApprovalQueueItem object as dict (must include id,
                     action_id, status, reviewed_by, reviewed_at, etc.)
        
        Requirements: 7.4, 2.7
        
        Example:
            await EventBroadcaster.publish_approval_status_changed({
                "id": "789e0123-e89b-12d3-a456-426614174000",
                "action_id": "456e7890-e89b-12d3-a456-426614174000",
                "status": "approved",
                "reviewed_by": "admin@example.com",
                "reviewed_at": "2024-01-15T10:40:00Z",
                ...
            })
        """
        event_data = {
            "type": "approval_status_changed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "approval": EventBroadcaster._serialize_event_data(approval)
            }
        }
        await publish_event(EventChannel.APPROVAL_STATUS_CHANGED, event_data)
        
        # Invalidate ETags for approval-related endpoints
        # Requirements: 2.7
        invalidate_etag = _get_invalidate_etag()
        await invalidate_etag("/api/approvals/")
        await invalidate_etag("/api/dashboard/summary")
        
        logger.info(
            "Event published: approval_status_changed (id=%s, status=%s)",
            approval.get("id"),
            approval.get("status")
        )
    
    @staticmethod
    async def publish_savings_updated(
        savings: dict[str, Any],
        delta: dict[str, Any] | None = None
    ) -> None:
        """
        Publish when savings data is recalculated.
        
        Args:
            savings: Complete SavingsSummary object as dict (must include
                    total_savings_this_month, actions_taken_count,
                    anomalies_detected_count, etc.)
            delta: Optional dict with changes since last update (e.g.,
                  {"total_savings_this_month": 1000.00, "actions_taken_count": 1})
        
        Requirements: 7.5, 2.7
        
        Example:
            await EventBroadcaster.publish_savings_updated({
                "total_savings_this_month": 50000.00,
                "actions_taken_count": 10,
                "anomalies_detected_count": 15,
                ...
            }, delta={"total_savings_this_month": 5000.00, "actions_taken_count": 1})
        """
        event_data = {
            "type": "savings_updated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "savings": EventBroadcaster._serialize_event_data(savings),
                "delta": EventBroadcaster._serialize_event_data(delta) if delta else None
            }
        }
        await publish_event(EventChannel.SAVINGS_UPDATED, event_data)
        
        # Invalidate ETags for savings-related endpoints
        # Requirements: 2.7
        invalidate_etag = _get_invalidate_etag()
        await invalidate_etag("/api/savings/summary")
        await invalidate_etag("/api/dashboard/summary")
        
        logger.info(
            "Event published: savings_updated (total=%s, delta=%s)",
            savings.get("total_savings_this_month"),
            delta.get("total_savings_this_month") if delta else None
        )
    
    @staticmethod
    async def publish_system_status_changed(
        status: dict[str, Any],
        changes: list[str] | None = None
    ) -> None:
        """
        Publish when system status changes.
        
        Args:
            status: Complete SystemStatus object as dict (must include status, env,
                   models, deepseek_calls_this_hour, etc.)
            changes: Optional list of what changed (e.g., ["models", "budget_remaining"])
        
        Requirements: 7.5 (implied by event channel definition), 2.7
        
        Example:
            await EventBroadcaster.publish_system_status_changed({
                "status": "operational",
                "env": "production",
                "models": [...],
                "deepseek_calls_this_hour": 45,
                "deepseek_budget_remaining": 955,
                ...
            }, changes=["deepseek_calls_this_hour"])
        """
        event_data = {
            "type": "system_status_changed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "status": EventBroadcaster._serialize_event_data(status),
                "changes": changes or []
            }
        }
        await publish_event(EventChannel.SYSTEM_STATUS_CHANGED, event_data)
        
        # Invalidate ETags for system status endpoints
        # Requirements: 2.7
        invalidate_etag = _get_invalidate_etag()
        await invalidate_etag("/api/system/status")
        await invalidate_etag("/api/dashboard/summary")
        
        logger.info(
            "Event published: system_status_changed (status=%s, changes=%s)",
            status.get("status"),
            changes
        )
    
    @staticmethod
    def _serialize_event_data(data: Any) -> Any:
        """
        Serialize event data for JSON encoding.
        
        Handles special types like UUID, datetime, Decimal that need conversion
        before JSON serialization. This is called automatically by publish_event
        in redis_client.py, but we do it here for consistency.
        
        Args:
            data: Data to serialize (dict, list, or primitive)
        
        Returns:
            JSON-serializable version of the data
        """
        if data is None:
            return None
        
        if isinstance(data, dict):
            return {
                key: EventBroadcaster._serialize_event_data(value)
                for key, value in data.items()
            }
        
        if isinstance(data, list):
            return [EventBroadcaster._serialize_event_data(item) for item in data]
        
        if isinstance(data, UUID):
            return str(data)
        
        if isinstance(data, datetime):
            return data.isoformat()
        
        # Decimal, int, float, str, bool pass through
        # (json.dumps with default=str in redis_client handles Decimal)
        return data
