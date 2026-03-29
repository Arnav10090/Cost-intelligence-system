"""
ETag Middleware — HTTP caching with ETag generation and validation.

This middleware implements ETag-based HTTP caching for GET endpoints:
1. Generates ETags using SHA-256 hash of response body
2. Compares If-None-Match headers with current ETag
3. Returns 304 Not Modified when ETags match
4. Supports Redis-based ETag invalidation tracking
5. Gracefully degrades when disabled - responses work normally without ETags
6. Records cache hits and misses for monitoring

Requirements: 2.1, 2.2, 2.3, 2.7, 8.2, 8.7, 9.4
"""
import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from services.redis_client import get_redis

logger = logging.getLogger(__name__)


class ETagMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for ETag-based HTTP caching.
    
    This middleware intercepts GET requests and responses to implement
    conditional HTTP caching using ETags. When a client sends an If-None-Match
    header matching the current resource ETag, the server returns 304 Not Modified
    with no body, saving bandwidth and processing time.
    
    Requirements: 2.1, 2.2, 2.3
    
    Example:
        app.add_middleware(ETagMiddleware)
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Intercept GET requests and responses for ETag handling.
        
        Flow:
        1. Check if request is GET method
        2. Record API call for monitoring
        3. Check if client sent If-None-Match header
        4. Call next middleware/endpoint to get response
        5. Generate ETag from response body
        6. Compare with If-None-Match header
        7. Return 304 if match, otherwise return 200 with ETag header
        8. Record cache hits/misses for monitoring
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/endpoint in chain
        
        Returns:
            Response with ETag header or 304 Not Modified
        
        Requirements: 2.1, 2.2, 2.3, 8.1, 8.2, 8.7
        """
        # Record API call for monitoring (Requirements 8.1)
        endpoint_path = request.url.path
        try:
            from services.metrics_collector import get_metrics_collector
            metrics_collector = get_metrics_collector()
            metrics_collector.record_api_call(endpoint_path)
        except Exception as e:
            logger.debug("Failed to record API call: %s", e)
        
        # Only apply ETag logic to GET requests
        if request.method != "GET":
            return await call_next(request)
        
        # Get If-None-Match header from client
        client_etag = request.headers.get("If-None-Match")
        
        # Call next middleware/endpoint to get response
        response = await call_next(request)
        
        # Only apply ETag to successful responses (200 OK)
        if response.status_code != 200:
            return response
        
        # Read response body to generate ETag
        # Note: We need to consume the response body, so we'll reconstruct it
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk
        
        # Generate ETag from response body
        current_etag = generate_etag(response_body)
        
        # Check if ETag matches client's cached version
        if client_etag and client_etag == current_etag:
            # ETags match — return 304 Not Modified with no body
            logger.debug(
                "ETag match for %s: %s — returning 304",
                endpoint_path,
                current_etag
            )
            
            # Record cache hit for monitoring (Requirements 8.2, 8.7)
            try:
                from services.metrics_collector import get_metrics_collector
                metrics_collector = get_metrics_collector()
                metrics_collector.record_cache_hit(endpoint_path)
            except Exception as e:
                logger.debug("Failed to record cache hit: %s", e)
            
            return Response(
                status_code=304,
                headers={
                    "ETag": current_etag,
                    "Cache-Control": "no-cache",  # Must revalidate with server
                }
            )
        
        # ETags don't match or no client ETag — return 200 with ETag header
        logger.debug(
            "ETag generated for %s: %s",
            endpoint_path,
            current_etag
        )
        
        # Record cache miss for monitoring (Requirements 8.2, 8.7)
        try:
            from services.metrics_collector import get_metrics_collector
            metrics_collector = get_metrics_collector()
            metrics_collector.record_cache_miss(endpoint_path)
        except Exception as e:
            logger.debug("Failed to record cache miss: %s", e)
        
        # Reconstruct response with ETag header
        return Response(
            content=response_body,
            status_code=200,
            headers={
                **dict(response.headers),
                "ETag": current_etag,
                "Cache-Control": "no-cache",  # Must revalidate with server
            },
            media_type=response.media_type,
        )


def generate_etag(content: bytes) -> str:
    """
    Generate ETag from response content using SHA-256.
    
    The ETag is a quoted string containing the first 16 characters of the
    SHA-256 hash of the response body. This provides a unique identifier
    for the resource version while keeping the ETag header reasonably short.
    
    Args:
        content: Response body as bytes
    
    Returns:
        ETag string in format: "abc123def456..."
    
    Requirements: 2.1
    
    Example:
        >>> generate_etag(b'{"data": "example"}')
        '"a1b2c3d4e5f6g7h8"'
    """
    # Generate SHA-256 hash of content
    hash_obj = hashlib.sha256(content)
    hash_hex = hash_obj.hexdigest()
    
    # Use first 16 characters for ETag (sufficient uniqueness, shorter header)
    etag = f'"{hash_hex[:16]}"'
    
    return etag


async def invalidate_etag(endpoint: str) -> None:
    """
    Invalidate cached ETag for specific endpoint.
    
    This function marks an endpoint's ETag as invalidated by storing a timestamp
    in Redis. The middleware doesn't actively use this yet, but it provides
    infrastructure for future cache invalidation strategies.
    
    Redis key structure: ci:etag:{endpoint_path}
    Value: ISO 8601 timestamp of invalidation
    TTL: 3600 seconds (1 hour)
    
    Args:
        endpoint: API endpoint path (e.g., "/api/savings/summary")
    
    Requirements: 2.7
    
    Example:
        await invalidate_etag("/api/savings/summary")
    """
    try:
        redis = get_redis()
        key = f"ci:etag:{endpoint}"
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Store invalidation timestamp with 1 hour TTL
        await redis.setex(key, 3600, timestamp)
        
        logger.info("ETag invalidated for endpoint: %s", endpoint)
    except Exception as e:
        # Don't raise — ETag invalidation should not block main flow
        logger.error("Failed to invalidate ETag for %s: %s", endpoint, e)


async def get_etag_invalidation_time(endpoint: str) -> str | None:
    """
    Get the timestamp when an endpoint's ETag was last invalidated.
    
    This can be used to implement more sophisticated caching strategies
    where the middleware checks if the ETag was invalidated after the
    client's cached version.
    
    Args:
        endpoint: API endpoint path
    
    Returns:
        ISO 8601 timestamp string or None if not invalidated
    
    Requirements: 2.7
    """
    try:
        redis = get_redis()
        key = f"ci:etag:{endpoint}"
        timestamp = await redis.get(key)
        return timestamp
    except Exception as e:
        logger.error("Failed to get ETag invalidation time for %s: %s", endpoint, e)
        return None
