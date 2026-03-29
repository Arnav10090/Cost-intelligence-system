"""
Metrics Collector — Monitoring and metrics for API call optimization.

This module tracks and exposes metrics for the API call optimization feature:
- Total API calls per minute
- Cache hit rate by endpoint
- Active WebSocket connections
- WebSocket message broadcast count

Requirements: 8.1, 8.2, 8.3, 8.4
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class OptimizationMetrics(BaseModel):
    """
    Metrics for monitoring API call optimization.
    
    This schema defines all metrics tracked for the optimization feature,
    including API calls, cache performance, WebSocket activity, and
    performance measurements.
    
    Requirements: 8.1, 8.2, 8.3, 8.4
    """
    
    # API call metrics
    total_api_calls_per_minute: float = Field(
        description="Average API calls per minute over the last 5 minutes"
    )
    api_calls_by_endpoint: Dict[str, int] = Field(
        default_factory=dict,
        description="Total API calls grouped by endpoint path"
    )
    
    # Cache metrics
    cache_hit_rate: float = Field(
        description="Overall cache hit rate (0.0 to 1.0)"
    )
    cache_hits_by_endpoint: Dict[str, int] = Field(
        default_factory=dict,
        description="Cache hits grouped by endpoint path"
    )
    cache_misses_by_endpoint: Dict[str, int] = Field(
        default_factory=dict,
        description="Cache misses grouped by endpoint path"
    )
    
    # WebSocket metrics
    active_websocket_connections: int = Field(
        description="Number of currently connected WebSocket clients"
    )
    websocket_messages_sent: int = Field(
        description="Total WebSocket messages broadcast since startup"
    )
    websocket_reconnections: int = Field(
        default=0,
        description="Total WebSocket reconnection attempts"
    )
    
    # Performance metrics
    aggregated_endpoint_p95_latency_ms: float = Field(
        default=0.0,
        description="95th percentile latency for aggregated endpoint in milliseconds"
    )
    websocket_broadcast_latency_ms: float = Field(
        default=0.0,
        description="Average WebSocket broadcast latency in milliseconds"
    )
    
    # Comparison metrics
    baseline_calls_per_minute: float = Field(
        default=36.0,
        description="Baseline API calls per minute before optimization"
    )
    reduction_percentage: float = Field(
        description="Percentage reduction in API calls compared to baseline"
    )
    
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when metrics were collected"
    )


class MetricsCollector:
    """
    Collects and tracks optimization metrics.
    
    This singleton class maintains counters and timers for all optimization
    metrics. It provides methods to record events and calculate aggregated
    statistics.
    
    Requirements: 8.1, 8.2, 8.3, 8.4
    """
    
    def __init__(self):
        """Initialize metrics collector with zero counters."""
        # API call tracking
        self._api_calls: list[tuple[float, str]] = []  # (timestamp, endpoint)
        self._api_calls_by_endpoint: Dict[str, int] = defaultdict(int)
        
        # Cache tracking
        self._cache_hits_by_endpoint: Dict[str, int] = defaultdict(int)
        self._cache_misses_by_endpoint: Dict[str, int] = defaultdict(int)
        
        # WebSocket tracking
        self._websocket_messages_sent: int = 0
        self._websocket_reconnections: int = 0
        self._websocket_broadcast_latencies: list[float] = []
        
        # Aggregated endpoint latency tracking
        self._aggregated_endpoint_latencies: list[float] = []
        
        logger.info("MetricsCollector initialized")
    
    def record_api_call(self, endpoint: str) -> None:
        """
        Record an API call to a specific endpoint.
        
        Args:
            endpoint: API endpoint path (e.g., "/api/savings/summary")
        
        Requirements: 8.1
        """
        current_time = time.time()
        self._api_calls.append((current_time, endpoint))
        self._api_calls_by_endpoint[endpoint] += 1
        
        # Clean up old entries (keep last 5 minutes)
        cutoff_time = current_time - 300  # 5 minutes
        self._api_calls = [
            (ts, ep) for ts, ep in self._api_calls if ts > cutoff_time
        ]
    
    def record_cache_hit(self, endpoint: str) -> None:
        """
        Record a cache hit (304 Not Modified response).
        
        Args:
            endpoint: API endpoint path
        
        Requirements: 8.2
        """
        self._cache_hits_by_endpoint[endpoint] += 1
        logger.debug("Cache hit recorded for endpoint: %s", endpoint)
    
    def record_cache_miss(self, endpoint: str) -> None:
        """
        Record a cache miss (200 OK response with new ETag).
        
        Args:
            endpoint: API endpoint path
        
        Requirements: 8.2
        """
        self._cache_misses_by_endpoint[endpoint] += 1
        logger.debug("Cache miss recorded for endpoint: %s", endpoint)
    
    def record_websocket_message_sent(self) -> None:
        """
        Record a WebSocket message broadcast.
        
        Requirements: 8.4
        """
        self._websocket_messages_sent += 1
    
    def record_websocket_reconnection(self) -> None:
        """
        Record a WebSocket reconnection attempt.
        
        Requirements: 8.3 (implied by connection tracking)
        """
        self._websocket_reconnections += 1
        logger.debug("WebSocket reconnection recorded")
    
    def record_websocket_broadcast_latency(self, latency_ms: float) -> None:
        """
        Record WebSocket broadcast latency.
        
        Args:
            latency_ms: Latency in milliseconds
        
        Requirements: 8.4 (performance tracking)
        """
        self._websocket_broadcast_latencies.append(latency_ms)
        
        # Keep only last 100 measurements
        if len(self._websocket_broadcast_latencies) > 100:
            self._websocket_broadcast_latencies = self._websocket_broadcast_latencies[-100:]
    
    def record_aggregated_endpoint_latency(self, latency_ms: float) -> None:
        """
        Record aggregated endpoint latency.
        
        Args:
            latency_ms: Latency in milliseconds
        
        Requirements: 8.1 (performance tracking)
        """
        self._aggregated_endpoint_latencies.append(latency_ms)
        
        # Keep only last 100 measurements
        if len(self._aggregated_endpoint_latencies) > 100:
            self._aggregated_endpoint_latencies = self._aggregated_endpoint_latencies[-100:]
    
    def get_metrics(self, active_websocket_connections: int) -> OptimizationMetrics:
        """
        Get current optimization metrics.
        
        Args:
            active_websocket_connections: Current number of active WebSocket connections
                                         (obtained from WebSocketManager)
        
        Returns:
            OptimizationMetrics object with all current metrics
        
        Requirements: 8.1, 8.2, 8.3, 8.4
        """
        # Calculate API calls per minute
        current_time = time.time()
        cutoff_time = current_time - 300  # Last 5 minutes
        recent_calls = [ts for ts, _ in self._api_calls if ts > cutoff_time]
        
        if recent_calls:
            time_window_minutes = (current_time - min(recent_calls)) / 60
            total_api_calls_per_minute = len(recent_calls) / max(time_window_minutes, 1)
        else:
            total_api_calls_per_minute = 0.0
        
        # Calculate cache hit rate
        total_hits = sum(self._cache_hits_by_endpoint.values())
        total_misses = sum(self._cache_misses_by_endpoint.values())
        total_requests = total_hits + total_misses
        
        if total_requests > 0:
            cache_hit_rate = total_hits / total_requests
        else:
            cache_hit_rate = 0.0
        
        # Calculate reduction percentage
        baseline = 36.0
        if baseline > 0:
            reduction_percentage = ((baseline - total_api_calls_per_minute) / baseline) * 100
        else:
            reduction_percentage = 0.0
        
        # Calculate p95 latency for aggregated endpoint
        if self._aggregated_endpoint_latencies:
            sorted_latencies = sorted(self._aggregated_endpoint_latencies)
            p95_index = int(len(sorted_latencies) * 0.95)
            aggregated_endpoint_p95_latency_ms = sorted_latencies[p95_index]
        else:
            aggregated_endpoint_p95_latency_ms = 0.0
        
        # Calculate average WebSocket broadcast latency
        if self._websocket_broadcast_latencies:
            websocket_broadcast_latency_ms = (
                sum(self._websocket_broadcast_latencies) / 
                len(self._websocket_broadcast_latencies)
            )
        else:
            websocket_broadcast_latency_ms = 0.0
        
        # Log warning if cache hit rate is below 30%
        # Requirements: 8.7
        if total_requests > 10 and cache_hit_rate < 0.30:
            logger.warning(
                "Cache hit rate below 30%%: %.2f%% (hits=%d, misses=%d)",
                cache_hit_rate * 100,
                total_hits,
                total_misses
            )
        
        return OptimizationMetrics(
            total_api_calls_per_minute=round(total_api_calls_per_minute, 2),
            api_calls_by_endpoint=dict(self._api_calls_by_endpoint),
            cache_hit_rate=round(cache_hit_rate, 4),
            cache_hits_by_endpoint=dict(self._cache_hits_by_endpoint),
            cache_misses_by_endpoint=dict(self._cache_misses_by_endpoint),
            active_websocket_connections=active_websocket_connections,
            websocket_messages_sent=self._websocket_messages_sent,
            websocket_reconnections=self._websocket_reconnections,
            aggregated_endpoint_p95_latency_ms=round(aggregated_endpoint_p95_latency_ms, 2),
            websocket_broadcast_latency_ms=round(websocket_broadcast_latency_ms, 2),
            baseline_calls_per_minute=36.0,
            reduction_percentage=round(reduction_percentage, 2),
            timestamp=datetime.now(timezone.utc)
        )
    
    def reset_metrics(self) -> None:
        """
        Reset all metrics to zero.
        
        This is useful for testing or when starting a new measurement period.
        """
        self._api_calls.clear()
        self._api_calls_by_endpoint.clear()
        self._cache_hits_by_endpoint.clear()
        self._cache_misses_by_endpoint.clear()
        self._websocket_messages_sent = 0
        self._websocket_reconnections = 0
        self._websocket_broadcast_latencies.clear()
        self._aggregated_endpoint_latencies.clear()
        logger.info("Metrics reset")


# Global singleton instance
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """
    Get the global MetricsCollector singleton instance.
    
    Returns:
        MetricsCollector instance
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector
