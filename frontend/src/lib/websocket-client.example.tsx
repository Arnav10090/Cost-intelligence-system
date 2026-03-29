/**
 * Example usage of WebSocket client and React hook.
 * 
 * This file demonstrates how to use the WebSocket client in React components.
 * It is not part of the production code, just for reference.
 */

'use client';

import { useEffect } from 'react';
import { useWebSocket, getWebSocketUrl, WebSocketMessage } from './websocket-client';

/**
 * Example component showing WebSocket integration.
 */
export function WebSocketExample() {
  const { 
    isConnected, 
    connectionState, 
    lastMessage, 
    error,
    shouldFallbackToPolling 
  } = useWebSocket(getWebSocketUrl());

  // Handle different message types
  useEffect(() => {
    if (!lastMessage) return;

    switch (lastMessage.type) {
      case 'anomaly_created':
        console.log('New anomaly detected:', lastMessage.data);
        // Update anomaly list in UI
        break;
      
      case 'action_executed':
        console.log('Action executed:', lastMessage.data);
        // Update action log in UI
        break;
      
      case 'approval_pending':
        console.log('Approval pending:', lastMessage.data);
        // Update approval queue in UI
        break;
      
      case 'savings_updated':
        console.log('Savings updated:', lastMessage.data);
        // Update savings counter in UI
        break;
      
      case 'system_status_changed':
        console.log('System status changed:', lastMessage.data);
        // Update system status in UI
        break;
    }
  }, [lastMessage]);

  // Handle fallback to polling
  useEffect(() => {
    if (shouldFallbackToPolling) {
      console.warn('WebSocket failed, falling back to polling mode');
      // Enable polling logic here
    }
  }, [shouldFallbackToPolling]);

  return (
    <div style={{ padding: '1rem', border: '1px solid #ccc', borderRadius: '4px' }}>
      <h3>WebSocket Status</h3>
      <p>
        <strong>State:</strong> {connectionState}
        {isConnected && ' ✓'}
      </p>
      {error && (
        <p style={{ color: 'red' }}>
          <strong>Error:</strong> {error.message}
        </p>
      )}
      {shouldFallbackToPolling && (
        <p style={{ color: 'orange' }}>
          <strong>Note:</strong> Using polling mode (WebSocket unavailable)
        </p>
      )}
      {lastMessage && (
        <div>
          <h4>Last Message:</h4>
          <pre style={{ background: '#f5f5f5', padding: '0.5rem', fontSize: '0.875rem' }}>
            {JSON.stringify(lastMessage, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

/**
 * Example of using WebSocket client directly (without React hook).
 */
export function directWebSocketExample() {
  const { WebSocketClient } = require('./websocket-client');
  
  const client = new WebSocketClient(getWebSocketUrl(), {
    maxRetries: 3,
    initialRetryDelay: 1000,
    maxRetryDelay: 30000,
  });

  // Register event handlers
  client.on('anomaly_created', (data: unknown) => {
    console.log('Anomaly created:', data);
  });

  client.on('action_executed', (data: unknown) => {
    console.log('Action executed:', data);
  });

  client.on('stateChange', (state: unknown) => {
    console.log('Connection state:', state);
  });

  client.on('maxRetriesReached', () => {
    console.warn('Max retries reached, falling back to polling');
  });

  // Connect
  client.connect();

  // Later, disconnect
  // client.disconnect();
}
