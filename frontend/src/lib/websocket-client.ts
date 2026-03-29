/**
 * WebSocket client for real-time dashboard updates.
 * 
 * Provides connection management, reconnection with exponential backoff,
 * and event handler registration for WebSocket messages.
 * 
 * Requirements: 1.4, 1.5
 */

// ── Types ───────────────────────────────────────────────────────────────────

export type ConnectionState = 'connected' | 'connecting' | 'disconnected';

export type MessageType = 
  | 'anomaly_created'
  | 'action_executed'
  | 'approval_pending'
  | 'savings_updated'
  | 'system_status_changed';

export interface WebSocketMessage {
  type: MessageType;
  timestamp: string;
  data: unknown;
}

export interface WebSocketOptions {
  /** Maximum number of reconnection attempts (default: 3) */
  maxRetries?: number;
  /** Initial retry delay in milliseconds (default: 1000) */
  initialRetryDelay?: number;
  /** Maximum retry delay in milliseconds (default: 30000) */
  maxRetryDelay?: number;
  /** Authentication token for WebSocket connection */
  authToken?: string;
}

type EventHandler = (data: unknown) => void;

// ── WebSocket Client ────────────────────────────────────────────────────────

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private options: Required<WebSocketOptions>;
  private connectionState: ConnectionState = 'disconnected';
  private retryCount = 0;
  private retryTimeout: NodeJS.Timeout | null = null;
  private eventHandlers: Map<string, Set<EventHandler>> = new Map();
  private reconnectOnClose = true;

  constructor(url: string, options: WebSocketOptions = {}) {
    this.url = url;
    this.options = {
      maxRetries: options.maxRetries ?? 3,
      initialRetryDelay: options.initialRetryDelay ?? 1000,
      maxRetryDelay: options.maxRetryDelay ?? 30000,
      authToken: options.authToken ?? '',
    };
  }

  /**
   * Establish WebSocket connection with authentication.
   * Implements exponential backoff reconnection strategy.
   * 
   * Requirements: 9.2, 9.3 - Detects WebSocket support before attempting connection
   */
  async connect(): Promise<void> {
    if (this.connectionState === 'connected' || this.connectionState === 'connecting') {
      return;
    }

    // Detect WebSocket support before attempting connection (Requirements 9.3)
    if (!isWebSocketSupported()) {
      console.warn('[WebSocket] WebSocket not supported in this browser, falling back to polling');
      this.notifyMaxRetriesReached(); // Trigger fallback to polling
      return;
    }

    this.connectionState = 'connecting';
    this.notifyStateChange();

    try {
      // Add auth token as query parameter if provided
      const wsUrl = this.options.authToken
        ? `${this.url}?token=${encodeURIComponent(this.options.authToken)}`
        : this.url;

      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.connectionState = 'connected';
        this.retryCount = 0; // Reset retry count on successful connection
        this.notifyStateChange();
        console.log('[WebSocket] Connected to', this.url);
      };

      this.ws.onmessage = (event) => {
        this.handleMessage(event.data);
      };

      this.ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
      };

      this.ws.onclose = () => {
        const wasConnected = this.connectionState === 'connected';
        this.connectionState = 'disconnected';
        this.notifyStateChange();
        console.log('[WebSocket] Disconnected');

        // Attempt reconnection if enabled and we were previously connected
        if (this.reconnectOnClose && wasConnected) {
          this.scheduleReconnect();
        }
      };
    } catch (error) {
      this.connectionState = 'disconnected';
      this.notifyStateChange();
      console.error('[WebSocket] Connection failed:', error);
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect WebSocket and prevent automatic reconnection.
   */
  disconnect(): void {
    this.reconnectOnClose = false;
    
    if (this.retryTimeout) {
      clearTimeout(this.retryTimeout);
      this.retryTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.connectionState = 'disconnected';
    this.notifyStateChange();
  }

  /**
   * Register an event handler for a specific message type.
   */
  on(eventType: string, handler: EventHandler): void {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, new Set());
    }
    this.eventHandlers.get(eventType)!.add(handler);
  }

  /**
   * Unregister an event handler for a specific message type.
   */
  off(eventType: string, handler: EventHandler): void {
    const handlers = this.eventHandlers.get(eventType);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.eventHandlers.delete(eventType);
      }
    }
  }

  /**
   * Get current connection state.
   */
  getConnectionState(): ConnectionState {
    return this.connectionState;
  }

  /**
   * Schedule reconnection with exponential backoff.
   * Backoff sequence: 1s, 2s, 4s, 8s, 16s, 30s (max)
   */
  private scheduleReconnect(): void {
    if (this.retryCount >= this.options.maxRetries) {
      console.warn('[WebSocket] Max retry attempts reached, falling back to polling mode');
      this.notifyMaxRetriesReached();
      return;
    }

    // Calculate delay with exponential backoff: initialDelay * 2^retryCount
    const delay = Math.min(
      this.options.initialRetryDelay * Math.pow(2, this.retryCount),
      this.options.maxRetryDelay
    );

    this.retryCount++;
    console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.retryCount}/${this.options.maxRetries})`);

    this.retryTimeout = setTimeout(() => {
      this.reconnectOnClose = true; // Re-enable reconnection for this attempt
      this.connect();
    }, delay);
  }

  /**
   * Handle incoming WebSocket message.
   * Validates message structure and dispatches to registered handlers.
   */
  private handleMessage(data: string): void {
    try {
      const message = JSON.parse(data) as WebSocketMessage;

      // Validate message structure (Requirements 6.6)
      if (!this.isValidMessage(message)) {
        console.error('[WebSocket] Invalid message structure:', message);
        // Continue processing other messages (Requirements 6.7)
        return;
      }

      // Dispatch to registered handlers
      const handlers = this.eventHandlers.get(message.type);
      if (handlers) {
        handlers.forEach(handler => {
          try {
            handler(message.data);
          } catch (error) {
            console.error(`[WebSocket] Error in handler for ${message.type}:`, error);
          }
        });
      }

      // Also notify generic 'message' handlers
      const messageHandlers = this.eventHandlers.get('message');
      if (messageHandlers) {
        messageHandlers.forEach(handler => {
          try {
            handler(message);
          } catch (error) {
            console.error('[WebSocket] Error in message handler:', error);
          }
        });
      }
    } catch (error) {
      console.error('[WebSocket] Failed to parse message:', error);
      // Continue processing other messages (Requirements 6.7)
    }
  }

  /**
   * Validate WebSocket message structure.
   * Requirements: 6.1, 6.6
   */
  private isValidMessage(message: unknown): message is WebSocketMessage {
    if (!message || typeof message !== 'object') {
      return false;
    }

    const msg = message as Record<string, unknown>;
    
    // Check required fields: type, timestamp, data
    if (typeof msg.type !== 'string' || !msg.type) {
      return false;
    }

    // Allow empty timestamp for ping messages (keep-alive)
    if (msg.type === 'ping') {
      return true;
    }

    if (typeof msg.timestamp !== 'string' || !msg.timestamp) {
      return false;
    }

    if (!('data' in msg)) {
      return false;
    }

    return true;
  }

  /**
   * Notify state change handlers.
   */
  private notifyStateChange(): void {
    const handlers = this.eventHandlers.get('stateChange');
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(this.connectionState);
        } catch (error) {
          console.error('[WebSocket] Error in stateChange handler:', error);
        }
      });
    }
  }

  /**
   * Notify max retries reached handlers.
   */
  private notifyMaxRetriesReached(): void {
    const handlers = this.eventHandlers.get('maxRetriesReached');
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(null);
        } catch (error) {
          console.error('[WebSocket] Error in maxRetriesReached handler:', error);
        }
      });
    }
  }
}


// ── React Hook ──────────────────────────────────────────────────────────────

import { useEffect, useState, useRef } from 'react';

export interface UseWebSocketResult {
  /** Whether WebSocket is currently connected */
  isConnected: boolean;
  /** Current connection state */
  connectionState: ConnectionState;
  /** Last received message */
  lastMessage: WebSocketMessage | null;
  /** Last error that occurred */
  error: Error | null;
  /** Whether max retries have been reached (should fall back to polling) */
  shouldFallbackToPolling: boolean;
}

/**
 * React hook for WebSocket integration.
 * 
 * Manages WebSocket connection lifecycle, state, and message handling.
 * Automatically connects on mount and disconnects on unmount.
 * 
 * Requirements: 1.4
 * 
 * @param url - WebSocket URL (e.g., 'ws://localhost:8000/ws/dashboard')
 * @param options - WebSocket configuration options
 * @returns WebSocket state and last message
 * 
 * @example
 * ```tsx
 * function Dashboard() {
 *   const { isConnected, lastMessage, shouldFallbackToPolling } = useWebSocket(
 *     'ws://localhost:8000/ws/dashboard'
 *   );
 * 
 *   useEffect(() => {
 *     if (lastMessage?.type === 'anomaly_created') {
 *       // Handle anomaly update
 *     }
 *   }, [lastMessage]);
 * 
 *   return <div>Status: {isConnected ? 'Connected' : 'Disconnected'}</div>;
 * }
 * ```
 */
export function useWebSocket(
  url: string,
  options: WebSocketOptions = {}
): UseWebSocketResult {
  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [shouldFallbackToPolling, setShouldFallbackToPolling] = useState(false);
  
  const clientRef = useRef<WebSocketClient | null>(null);

  useEffect(() => {
    // Create WebSocket client
    const client = new WebSocketClient(url, options);
    clientRef.current = client;

    // Register state change handler
    client.on('stateChange', (state) => {
      setConnectionState(state as ConnectionState);
    });

    // Register message handler
    client.on('message', (message) => {
      setLastMessage(message as WebSocketMessage);
    });

    // Register max retries handler
    client.on('maxRetriesReached', () => {
      setShouldFallbackToPolling(true);
      setError(new Error('WebSocket max retries reached, falling back to polling'));
    });

    // Connect
    client.connect().catch((err) => {
      setError(err instanceof Error ? err : new Error(String(err)));
    });

    // Cleanup on unmount
    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [url, options.authToken, options.maxRetries, options.initialRetryDelay, options.maxRetryDelay]);

  return {
    isConnected: connectionState === 'connected',
    connectionState,
    lastMessage,
    error,
    shouldFallbackToPolling,
  };
}


// ── Utility Functions ───────────────────────────────────────────────────────

/**
 * Check if WebSocket is supported in the current browser.
 * 
 * Requirements: 9.3 - Detect WebSocket support before attempting connection
 * 
 * @returns true if WebSocket is supported, false otherwise
 */
export function isWebSocketSupported(): boolean {
  // Check if we're in a browser environment
  if (typeof window === 'undefined') {
    return false;
  }

  // Check if WebSocket constructor exists
  if (typeof WebSocket === 'undefined') {
    return false;
  }

  // Additional check: try to access WebSocket.CONNECTING constant
  // This ensures WebSocket is not just defined but actually functional
  try {
    return typeof WebSocket.CONNECTING === 'number';
  } catch {
    return false;
  }
}

/**
 * Get WebSocket URL for the dashboard endpoint.
 * Automatically determines the correct URL based on the environment.
 * 
 * @returns WebSocket URL (e.g., 'ws://localhost:3000/ws/dashboard')
 */
export function getWebSocketUrl(): string {
  // In browser environment
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    
    // Use the Next.js proxy - connect to the same host as the frontend
    // Next.js will proxy /ws/* to the backend via next.config.ts rewrites
    return `${protocol}//${host}/ws/dashboard`;
  }
  
  // Server-side rendering fallback
  return 'ws://localhost:3000/ws/dashboard';
}
