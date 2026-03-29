"""
WebSocket Server — Real-time dashboard updates via WebSocket connections.

This module manages WebSocket connections for the Cost Intelligence dashboard,
providing real-time updates when data changes. It subscribes to Redis pub/sub
channels and broadcasts events to all connected clients. Records metrics for
monitoring.

Requirements: 1.1, 1.2, 1.3, 1.4, 7.6, 7.7, 8.3, 8.4
"""
import asyncio
import logging
from typing import Dict
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from services.redis_client import EventChannel, subscribe_to_events

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and event broadcasting.
    
    This class handles the lifecycle of WebSocket connections, including
    authentication, connection management, and broadcasting events from
    Redis pub/sub to connected clients.
    
    Requirements: 1.1, 1.2, 1.3
    """
    
    def __init__(self):
        """Initialize the WebSocket manager with empty connection pool."""
        # Map of client_id -> WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}
        # Background task for event listener
        self._listener_task: asyncio.Task | None = None
        logger.info("WebSocketManager initialized")
    
    async def connect(self, websocket: WebSocket, client_id: str | None = None) -> str:
        """
        Authenticate and register a new WebSocket connection.
        
        Args:
            websocket: FastAPI WebSocket connection object
            client_id: Optional client identifier (generated if not provided)
        
        Returns:
            client_id: Unique identifier for this connection
        
        Requirements: 1.2
        
        Note: Currently accepts all connections. In production, this should
        validate authentication tokens from headers or query parameters.
        """
        # Accept the WebSocket connection
        await websocket.accept()
        
        # Generate client_id if not provided
        if client_id is None:
            client_id = str(uuid4())
        
        # TODO: Add authentication validation here
        # For now, we accept all connections for MVP
        # In production, validate token from:
        # - websocket.headers.get("Authorization")
        # - websocket.query_params.get("token")
        
        # Register connection
        self.active_connections[client_id] = websocket
        logger.info("WebSocket connected: client_id=%s (total=%d)", 
                   client_id, len(self.active_connections))
        
        return client_id
    
    async def disconnect(self, client_id: str) -> None:
        """
        Remove client from active connections.
        
        Args:
            client_id: Unique identifier of the client to disconnect
        
        Requirements: 1.1
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info("WebSocket disconnected: client_id=%s (total=%d)", 
                       client_id, len(self.active_connections))
    
    async def broadcast(self, message: dict) -> None:
        """
        Send message to all connected clients.
        
        Args:
            message: JSON-serializable message to broadcast
        
        Requirements: 1.3, 7.7, 8.4
        
        Note: Handles disconnected clients gracefully by removing them
        from the active connections pool. Records metrics for monitoring.
        """
        if not self.active_connections:
            logger.debug("No active connections to broadcast to")
            return
        
        disconnected_clients = []
        
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
                logger.debug("Message sent to client_id=%s", client_id)
            except WebSocketDisconnect:
                logger.warning("Client disconnected during broadcast: client_id=%s", client_id)
                disconnected_clients.append(client_id)
            except Exception as e:
                logger.error("Error sending to client_id=%s: %s", client_id, e)
                disconnected_clients.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected_clients:
            await self.disconnect(client_id)
        
        # Record WebSocket message sent for monitoring (Requirements 8.4)
        try:
            from services.metrics_collector import get_metrics_collector
            metrics_collector = get_metrics_collector()
            metrics_collector.record_websocket_message_sent()
        except Exception as e:
            logger.debug("Failed to record WebSocket message: %s", e)
        
        logger.debug("Broadcast complete: sent=%d, failed=%d", 
                    len(self.active_connections), len(disconnected_clients))
    
    async def broadcast_to_client(self, client_id: str, message: dict) -> None:
        """
        Send message to specific client.
        
        Args:
            client_id: Unique identifier of the target client
            message: JSON-serializable message to send
        
        Requirements: 1.3
        """
        websocket = self.active_connections.get(client_id)
        
        if websocket is None:
            logger.warning("Client not found: client_id=%s", client_id)
            return
        
        try:
            await websocket.send_json(message)
            logger.debug("Message sent to client_id=%s", client_id)
        except WebSocketDisconnect:
            logger.warning("Client disconnected: client_id=%s", client_id)
            await self.disconnect(client_id)
        except Exception as e:
            logger.error("Error sending to client_id=%s: %s", client_id, e)
            await self.disconnect(client_id)
    
    async def start_event_listener(self) -> None:
        """
        Subscribe to Redis pub/sub and forward events to WebSocket clients.
        
        This method runs as a background task, listening to all Redis event
        channels and broadcasting received events to all connected WebSocket
        clients. It runs indefinitely until cancelled.
        
        Requirements: 7.6, 7.7
        
        Note: This should be started during application startup and cancelled
        during shutdown.
        """
        logger.info("Starting Redis event listener for WebSocket broadcasting")
        
        try:
            async for channel, event_data in subscribe_to_events(EventChannel.all_channels()):
                # Forward event to all connected WebSocket clients
                await self.broadcast(event_data)
                logger.debug("Event forwarded from Redis channel %s to %d clients",
                           channel, len(self.active_connections))
        
        except asyncio.CancelledError:
            logger.info("Event listener cancelled")
            raise
        except Exception as e:
            logger.error("Event listener error: %s", e)
            # Wait before potential restart
            await asyncio.sleep(5)
            raise
    
    def start_listener_task(self) -> None:
        """
        Start the event listener as a background task.
        
        This creates an asyncio Task that runs start_event_listener() in the
        background. The task should be cancelled during application shutdown.
        
        Requirements: 7.6
        """
        if self._listener_task is not None and not self._listener_task.done():
            logger.warning("Event listener task already running")
            return
        
        self._listener_task = asyncio.create_task(
            self.start_event_listener(),
            name="websocket_event_listener"
        )
        logger.info("Event listener task started")
    
    async def stop_listener_task(self) -> None:
        """
        Stop the event listener background task.
        
        This cancels the listener task and waits for it to complete.
        Should be called during application shutdown.
        
        Requirements: 7.6
        """
        if self._listener_task is None:
            return
        
        if not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Event listener task stopped")
    
    def get_connection_count(self) -> int:
        """
        Get the number of active WebSocket connections.
        
        Returns:
            Number of currently connected clients
        
        Requirements: 8.3 (monitoring)
        """
        return len(self.active_connections)


# Global singleton instance
_websocket_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """
    Get the global WebSocketManager singleton instance.
    
    Returns:
        WebSocketManager instance
    
    Note: The manager is created on first access. In production, this should
    be initialized during application startup.
    """
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
