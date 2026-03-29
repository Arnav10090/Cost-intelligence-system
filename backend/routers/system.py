"""
System router — system-level endpoints including optimization metrics.

This router provides endpoints for system monitoring, health checks, and
optimization metrics tracking.

Requirements: 8.5
"""
from fastapi import APIRouter

from services.metrics_collector import OptimizationMetrics, get_metrics_collector
from services.websocket_server import get_websocket_manager

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/metrics", response_model=OptimizationMetrics)
async def get_optimization_metrics():
    """
    Get current API call optimization metrics.
    
    Returns comprehensive metrics including:
    - Total API calls per minute (current vs baseline)
    - Cache hit rate by endpoint
    - Active WebSocket connections
    - WebSocket message broadcast count
    - Performance metrics (latency)
    - Reduction percentage compared to baseline
    
    Requirements: 8.5
    
    Example response:
    {
        "total_api_calls_per_minute": 10.5,
        "api_calls_by_endpoint": {
            "/api/savings/summary": 5,
            "/api/anomalies/": 3,
            "/api/actions/": 2
        },
        "cache_hit_rate": 0.65,
        "cache_hits_by_endpoint": {
            "/api/savings/summary": 10,
            "/api/anomalies/": 5
        },
        "cache_misses_by_endpoint": {
            "/api/savings/summary": 5,
            "/api/anomalies/": 3
        },
        "active_websocket_connections": 3,
        "websocket_messages_sent": 45,
        "websocket_reconnections": 2,
        "aggregated_endpoint_p95_latency_ms": 150.5,
        "websocket_broadcast_latency_ms": 25.3,
        "baseline_calls_per_minute": 36.0,
        "reduction_percentage": 70.83,
        "timestamp": "2024-01-15T10:30:00Z"
    }
    """
    metrics_collector = get_metrics_collector()
    websocket_manager = get_websocket_manager()
    
    # Get current WebSocket connection count
    active_connections = websocket_manager.get_connection_count()
    
    # Get all metrics
    metrics = metrics_collector.get_metrics(active_connections)
    
    return metrics
