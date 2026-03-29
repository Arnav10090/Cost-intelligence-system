# WebSocket Client

Real-time dashboard updates via WebSocket connection with automatic reconnection and fallback to polling.

## Features

- ✅ **Connection Management**: Automatic connection establishment and lifecycle management
- ✅ **Exponential Backoff**: Reconnection with exponential backoff (1s, 2s, 4s, 8s, 16s, 30s max)
- ✅ **Event Handlers**: Type-safe event handler registration for different message types
- ✅ **Message Validation**: Validates incoming messages before processing (Requirements 6.6, 6.7)
- ✅ **Error Resilience**: Continues processing after validation failures
- ✅ **React Hook**: Easy integration with React components via `useWebSocket()` hook
- ✅ **Fallback Support**: Automatic fallback to polling after max retries

## Requirements

Implements requirements:
- **1.4**: WebSocket connection establishment and message handling
- **1.5**: Reconnection with exponential backoff
- **6.1**: Message structure validation (type, timestamp, data)
- **6.6**: Client-side message validation
- **6.7**: Error resilience (continue processing after validation failures)

## Usage

### React Hook (Recommended)

```tsx
import { useWebSocket, getWebSocketUrl } from '@/lib/websocket-client';

function Dashboard() {
  const { 
    isConnected, 
    connectionState,
    lastMessage, 
    error,
    shouldFallbackToPolling 
  } = useWebSocket(getWebSocketUrl());

  // Handle messages
  useEffect(() => {
    if (!lastMessage) return;

    switch (lastMessage.type) {
      case 'anomaly_created':
        // Update anomaly list
        break;
      case 'action_executed':
        // Update action log
        break;
      case 'savings_updated':
        // Update savings counter
        break;
    }
  }, [lastMessage]);

  // Handle fallback to polling
  useEffect(() => {
    if (shouldFallbackToPolling) {
      // Enable polling mode
    }
  }, [shouldFallbackToPolling]);

  return (
    <div>
      Status: {isConnected ? 'Connected' : 'Disconnected'}
    </div>
  );
}
```

### Direct Client Usage

```typescript
import { WebSocketClient, getWebSocketUrl } from '@/lib/websocket-client';

const client = new WebSocketClient(getWebSocketUrl(), {
  maxRetries: 3,
  initialRetryDelay: 1000,
  maxRetryDelay: 30000,
});

// Register event handlers
client.on('anomaly_created', (data) => {
  console.log('New anomaly:', data);
});

client.on('action_executed', (data) => {
  console.log('Action executed:', data);
});

client.on('stateChange', (state) => {
  console.log('Connection state:', state);
});

client.on('maxRetriesReached', () => {
  console.warn('Falling back to polling');
});

// Connect
await client.connect();

// Later, disconnect
client.disconnect();
```

## Message Types

The WebSocket server sends messages in the following format:

```typescript
interface WebSocketMessage {
  type: MessageType;
  timestamp: string;  // ISO 8601
  data: unknown;      // Message-specific payload
}

type MessageType = 
  | 'anomaly_created'
  | 'action_executed'
  | 'approval_pending'
  | 'savings_updated'
  | 'system_status_changed';
```

### Example Messages

**Anomaly Created:**
```json
{
  "type": "anomaly_created",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "id": "anom-123",
    "anomaly_type": "duplicate_payment",
    "severity": "HIGH",
    "cost_impact_inr": 50000
  }
}
```

**Action Executed:**
```json
{
  "type": "action_executed",
  "timestamp": "2024-01-15T10:31:00Z",
  "data": {
    "id": "act-456",
    "action_type": "payment_hold",
    "status": "completed",
    "cost_saved": 50000
  }
}
```

**Savings Updated:**
```json
{
  "type": "savings_updated",
  "timestamp": "2024-01-15T10:32:00Z",
  "data": {
    "total_savings_this_month": 1250000,
    "actions_taken_count": 15,
    "anomalies_detected_count": 23
  }
}
```

## Configuration Options

```typescript
interface WebSocketOptions {
  /** Maximum number of reconnection attempts (default: 3) */
  maxRetries?: number;
  
  /** Initial retry delay in milliseconds (default: 1000) */
  initialRetryDelay?: number;
  
  /** Maximum retry delay in milliseconds (default: 30000) */
  maxRetryDelay?: number;
  
  /** Authentication token for WebSocket connection */
  authToken?: string;
}
```

## Reconnection Strategy

The client implements exponential backoff for reconnection:

1. **First retry**: 1 second
2. **Second retry**: 2 seconds
3. **Third retry**: 4 seconds
4. **Fourth retry**: 8 seconds
5. **Fifth retry**: 16 seconds
6. **Sixth retry**: 30 seconds (max)

After **3 failed attempts**, the client stops retrying and signals that the application should fall back to polling mode.

## Connection States

```typescript
type ConnectionState = 'connected' | 'connecting' | 'disconnected';
```

- **connected**: WebSocket is connected and ready to receive messages
- **connecting**: Connection attempt in progress
- **disconnected**: Not connected (may be retrying)

## Error Handling

### Message Validation Errors

Invalid messages are logged but don't interrupt processing:

```typescript
// Invalid message (missing required fields)
{
  "type": "anomaly_created"
  // Missing: timestamp, data
}
// Result: Logged error, continues processing next messages
```

### Connection Errors

Connection failures trigger automatic reconnection with exponential backoff:

```typescript
client.on('stateChange', (state) => {
  if (state === 'disconnected') {
    // Will automatically retry with backoff
  }
});
```

### Max Retries Reached

After max retries, the application should fall back to polling:

```typescript
client.on('maxRetriesReached', () => {
  // Enable polling mode
  startPolling();
});
```

## Testing

To test the WebSocket client:

1. **Start the backend**: `cd cost-intelligence/backend && uvicorn main:app --reload`
2. **Start the frontend**: `cd cost-intelligence/frontend && npm run dev`
3. **Open browser console**: Check for WebSocket connection logs
4. **Trigger events**: Use the demo trigger to create anomalies and actions
5. **Verify messages**: Check that messages are received in real-time

## Integration with Dashboard Components

The WebSocket client should be integrated into dashboard components to replace polling:

```tsx
function SavingsCounter() {
  const { isConnected, lastMessage } = useWebSocket(getWebSocketUrl());
  const [savings, setSavings] = useState<SavingsSummary | null>(null);

  // Update savings when WebSocket message received
  useEffect(() => {
    if (lastMessage?.type === 'savings_updated') {
      setSavings(lastMessage.data as SavingsSummary);
    }
  }, [lastMessage]);

  // Disable polling when WebSocket is connected
  useEffect(() => {
    if (isConnected) {
      // Stop polling
    } else {
      // Start polling
    }
  }, [isConnected]);

  return <div>Total Savings: {savings?.total_savings_this_month}</div>;
}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React Component                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           useWebSocket() Hook                        │   │
│  │  - Manages connection state                          │   │
│  │  - Provides lastMessage                              │   │
│  │  - Signals fallback to polling                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         WebSocketClient Class                        │   │
│  │  - Connection management                             │   │
│  │  - Exponential backoff reconnection                  │   │
│  │  - Message validation                                │   │
│  │  - Event handler registration                        │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              WebSocket Connection
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend WebSocket Server                    │
│  - Authenticates connections                                 │
│  - Subscribes to Redis pub/sub                              │
│  - Broadcasts events to all clients                         │
└─────────────────────────────────────────────────────────────┘
```

## Next Steps

After implementing the WebSocket client, the next tasks are:

1. **Task 10**: Implement frontend cache manager with ETag support
2. **Task 11**: Implement request deduplicator
3. **Task 12**: Implement adaptive poller
4. **Task 14**: Integrate WebSocket client into dashboard components

## References

- Design Document: `.kiro/specs/api-call-optimization/design.md`
- Requirements: `.kiro/specs/api-call-optimization/requirements.md`
- Backend WebSocket Server: `cost-intelligence/backend/services/websocket_server.py`
- Backend WebSocket Endpoint: `cost-intelligence/backend/main.py` (line 312)
