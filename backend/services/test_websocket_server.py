"""
Unit tests for WebSocket server infrastructure.

Tests the WebSocketManager class for connection management, broadcasting,
and Redis event listener integration.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.websocket_server import WebSocketManager, get_websocket_manager


@pytest.fixture
def ws_manager():
    """Create a fresh WebSocketManager instance for each test."""
    return WebSocketManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestWebSocketManager:
    """Test suite for WebSocketManager class."""
    
    @pytest.mark.asyncio
    async def test_connect_generates_client_id(self, ws_manager, mock_websocket):
        """Test that connect() generates a client_id if not provided."""
        client_id = await ws_manager.connect(mock_websocket)
        
        assert client_id is not None
        assert isinstance(client_id, str)
        assert len(client_id) > 0
        assert client_id in ws_manager.active_connections
        assert ws_manager.active_connections[client_id] == mock_websocket
        mock_websocket.accept.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_uses_provided_client_id(self, ws_manager, mock_websocket):
        """Test that connect() uses provided client_id."""
        provided_id = "test-client-123"
        client_id = await ws_manager.connect(mock_websocket, provided_id)
        
        assert client_id == provided_id
        assert provided_id in ws_manager.active_connections
        mock_websocket.accept.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self, ws_manager, mock_websocket):
        """Test that disconnect() removes client from active connections."""
        client_id = await ws_manager.connect(mock_websocket)
        assert client_id in ws_manager.active_connections
        
        await ws_manager.disconnect(client_id)
        assert client_id not in ws_manager.active_connections
    
    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_client(self, ws_manager):
        """Test that disconnect() handles nonexistent client gracefully."""
        # Should not raise an exception
        await ws_manager.disconnect("nonexistent-client")
    
    @pytest.mark.asyncio
    async def test_broadcast_to_all_clients(self, ws_manager):
        """Test that broadcast() sends message to all connected clients."""
        # Connect multiple clients
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        
        client1 = await ws_manager.connect(ws1)
        client2 = await ws_manager.connect(ws2)
        
        # Broadcast message
        message = {"type": "test", "data": "hello"}
        await ws_manager.broadcast(message)
        
        # Verify both clients received the message
        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)
    
    @pytest.mark.asyncio
    async def test_broadcast_handles_disconnected_client(self, ws_manager):
        """Test that broadcast() removes disconnected clients."""
        from fastapi import WebSocketDisconnect
        
        # Connect two clients
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock(side_effect=WebSocketDisconnect())
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        
        client1 = await ws_manager.connect(ws1)
        client2 = await ws_manager.connect(ws2)
        
        assert len(ws_manager.active_connections) == 2
        
        # Broadcast message
        message = {"type": "test", "data": "hello"}
        await ws_manager.broadcast(message)
        
        # Client 1 should be removed, client 2 should still be connected
        assert client1 not in ws_manager.active_connections
        assert client2 in ws_manager.active_connections
        ws2.send_json.assert_called_once_with(message)
    
    @pytest.mark.asyncio
    async def test_broadcast_to_client(self, ws_manager, mock_websocket):
        """Test that broadcast_to_client() sends to specific client."""
        client_id = await ws_manager.connect(mock_websocket)
        
        message = {"type": "test", "data": "hello"}
        await ws_manager.broadcast_to_client(client_id, message)
        
        mock_websocket.send_json.assert_called_once_with(message)
    
    @pytest.mark.asyncio
    async def test_broadcast_to_nonexistent_client(self, ws_manager):
        """Test that broadcast_to_client() handles nonexistent client."""
        # Should not raise an exception
        message = {"type": "test", "data": "hello"}
        await ws_manager.broadcast_to_client("nonexistent", message)
    
    @pytest.mark.asyncio
    async def test_get_connection_count(self, ws_manager):
        """Test that get_connection_count() returns correct count."""
        assert ws_manager.get_connection_count() == 0
        
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        await ws_manager.connect(ws1)
        assert ws_manager.get_connection_count() == 1
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        await ws_manager.connect(ws2)
        assert ws_manager.get_connection_count() == 2
    
    @pytest.mark.asyncio
    async def test_start_listener_task(self, ws_manager):
        """Test that start_listener_task() creates background task."""
        with patch.object(ws_manager, 'start_event_listener', new_callable=AsyncMock) as mock_listener:
            # Make the mock listener run indefinitely
            async def mock_listener_impl():
                await asyncio.sleep(10)
            mock_listener.side_effect = mock_listener_impl
            
            ws_manager.start_listener_task()
            
            # Give the task a moment to start
            await asyncio.sleep(0.1)
            
            assert ws_manager._listener_task is not None
            assert not ws_manager._listener_task.done()
            
            # Clean up
            await ws_manager.stop_listener_task()
    
    @pytest.mark.asyncio
    async def test_stop_listener_task(self, ws_manager):
        """Test that stop_listener_task() cancels background task."""
        with patch.object(ws_manager, 'start_event_listener', new_callable=AsyncMock) as mock_listener:
            # Make the mock listener run indefinitely
            async def mock_listener_impl():
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    raise
            mock_listener.side_effect = mock_listener_impl
            
            ws_manager.start_listener_task()
            await asyncio.sleep(0.1)
            
            assert ws_manager._listener_task is not None
            assert not ws_manager._listener_task.done()
            
            # Stop the task
            await ws_manager.stop_listener_task()
            
            # Task should be done (cancelled)
            assert ws_manager._listener_task.done()


def test_get_websocket_manager_singleton():
    """Test that get_websocket_manager() returns singleton instance."""
    manager1 = get_websocket_manager()
    manager2 = get_websocket_manager()
    
    assert manager1 is manager2
    assert isinstance(manager1, WebSocketManager)
