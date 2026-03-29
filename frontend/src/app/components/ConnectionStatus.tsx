/**
 * Connection Status Component — displays WebSocket connection state.
 * 
 * Shows a visual indicator of the current connection status:
 * - WebSocket connected (green)
 * - Polling mode (yellow)
 * - Offline/disconnected (red)
 * 
 * Requirements: 8.6
 */

'use client';

import { useWebSocket, getWebSocketUrl, ConnectionState } from '@/lib/websocket-client';

// ── Types ───────────────────────────────────────────────────────────────────

interface ConnectionStatusProps {
  /** Optional className for styling */
  className?: string;
  /** Whether to show detailed status text (default: true) */
  showText?: boolean;
}

type StatusInfo = {
  label: string;
  color: string;
  bgColor: string;
  icon: string;
};

// ── Component ───────────────────────────────────────────────────────────────

export default function ConnectionStatus({ 
  className = '', 
  showText = true 
}: ConnectionStatusProps) {
  const { connectionState, shouldFallbackToPolling } = useWebSocket(getWebSocketUrl());

  // Determine status based on connection state
  const getStatusInfo = (): StatusInfo => {
    if (shouldFallbackToPolling) {
      return {
        label: 'Polling',
        color: 'text-yellow-700',
        bgColor: 'bg-yellow-100',
        icon: '🔄',
      };
    }

    switch (connectionState) {
      case 'connected':
        return {
          label: 'Connected',
          color: 'text-green-700',
          bgColor: 'bg-green-100',
          icon: '✓',
        };
      case 'connecting':
        return {
          label: 'Connecting...',
          color: 'text-blue-700',
          bgColor: 'bg-blue-100',
          icon: '⟳',
        };
      case 'disconnected':
      default:
        return {
          label: 'Offline',
          color: 'text-red-700',
          bgColor: 'bg-red-100',
          icon: '✗',
        };
    }
  };

  const status = getStatusInfo();

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {/* Status indicator dot */}
      <div className="flex items-center gap-1.5">
        <div
          className={`w-2 h-2 rounded-full ${
            connectionState === 'connected'
              ? 'bg-green-500 animate-pulse'
              : connectionState === 'connecting'
              ? 'bg-blue-500 animate-pulse'
              : shouldFallbackToPolling
              ? 'bg-yellow-500'
              : 'bg-red-500'
          }`}
          aria-label={`Connection status: ${status.label}`}
        />
        
        {showText && (
          <span className={`text-sm font-medium ${status.color}`}>
            {status.label}
          </span>
        )}
      </div>

      {/* Tooltip on hover */}
      {!showText && (
        <div className="group relative">
          <div className="invisible group-hover:visible absolute left-0 top-full mt-1 z-10">
            <div className={`px-2 py-1 rounded text-xs whitespace-nowrap ${status.bgColor} ${status.color}`}>
              {status.label}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ── Compact Variant ─────────────────────────────────────────────────────────

/**
 * Compact connection status badge for header/navbar.
 * Shows only the status dot with tooltip on hover.
 */
export function ConnectionStatusBadge({ className = '' }: { className?: string }) {
  return <ConnectionStatus className={className} showText={false} />;
}


// ── Detailed Variant ────────────────────────────────────────────────────────

/**
 * Detailed connection status panel with additional information.
 * Shows connection state, mode (WebSocket/Polling), and reconnection info.
 */
export function ConnectionStatusPanel({ className = '' }: { className?: string }) {
  const { connectionState, shouldFallbackToPolling, error } = useWebSocket(getWebSocketUrl());

  const getMode = (): string => {
    if (shouldFallbackToPolling) {
      return 'Polling Mode';
    }
    return connectionState === 'connected' ? 'WebSocket Mode' : 'Disconnected';
  };

  const getDescription = (): string => {
    if (shouldFallbackToPolling) {
      return 'Using HTTP polling for updates (WebSocket unavailable)';
    }

    switch (connectionState) {
      case 'connected':
        return 'Real-time updates via WebSocket';
      case 'connecting':
        return 'Establishing WebSocket connection...';
      case 'disconnected':
      default:
        return 'Connection lost. Attempting to reconnect...';
    }
  };

  return (
    <div className={`p-4 rounded-lg border ${className}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <ConnectionStatus showText={true} />
          </div>
          
          <div className="text-sm text-gray-600 mb-1">
            {getMode()}
          </div>
          
          <div className="text-xs text-gray-500">
            {getDescription()}
          </div>

          {error && (
            <div className="mt-2 text-xs text-red-600">
              Error: {error.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
