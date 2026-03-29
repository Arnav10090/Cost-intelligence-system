/**
 * Example usage of CacheManager and useCachedFetch hook.
 * 
 * This file demonstrates how to use the cache manager for HTTP caching
 * with ETag support and WebSocket-based cache invalidation.
 */

import React from 'react';
import { useCachedFetch, useWebSocketCacheInvalidation, cacheManager } from './cache-manager';
import { useWebSocket } from './websocket-client';

// ── Example 1: Basic Cached Fetch ──────────────────────────────────────────

interface SavingsSummary {
  total_savings_this_month: number;
  actions_taken_count: number;
  anomalies_detected_count: number;
}

function SavingsCounter() {
  const { data, loading, error, refetch } = useCachedFetch<SavingsSummary>(
    'http://localhost:8000/api/savings/summary'
  );

  if (loading) return <div>Loading savings...</div>;
  if (error) return <div>Error: {error.message}</div>;
  if (!data) return <div>No data</div>;

  return (
    <div>
      <h2>Savings Summary</h2>
      <p>Total Savings: ${data.total_savings_this_month}</p>
      <p>Actions Taken: {data.actions_taken_count}</p>
      <p>Anomalies Detected: {data.anomalies_detected_count}</p>
      <button onClick={refetch}>Refresh</button>
    </div>
  );
}

// ── Example 2: With Polling ────────────────────────────────────────────────

function AnomalyFeed() {
  const { data, loading, error } = useCachedFetch<Array<{ id: string; title: string }>>(
    'http://localhost:8000/api/anomalies/',
    {
      pollingInterval: 15000, // Poll every 15 seconds
    }
  );

  if (loading && !data) return <div>Loading anomalies...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h2>Recent Anomalies</h2>
      {loading && <span>Updating...</span>}
      <ul>
        {data?.map((anomaly) => (
          <li key={anomaly.id}>{anomaly.title}</li>
        ))}
      </ul>
    </div>
  );
}

// ── Example 3: With WebSocket Integration ──────────────────────────────────

function Dashboard() {
  // Connect to WebSocket for real-time updates
  const { isConnected, lastMessage, shouldFallbackToPolling } = useWebSocket(
    'ws://localhost:8000/ws/dashboard'
  );

  // Automatically invalidate cache when WebSocket messages arrive
  useWebSocketCacheInvalidation(lastMessage);

  // Fetch data with caching - will refetch when cache is invalidated
  const { data: savings } = useCachedFetch<SavingsSummary>(
    'http://localhost:8000/api/savings/summary',
    {
      // Only poll if WebSocket is not connected
      pollingInterval: shouldFallbackToPolling ? 10000 : 0,
    }
  );

  return (
    <div>
      <div>
        WebSocket Status: {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
        {shouldFallbackToPolling && ' (Polling Mode)'}
      </div>
      
      <div>
        <h2>Savings: ${savings?.total_savings_this_month || 0}</h2>
      </div>

      {lastMessage && (
        <div>
          Last Update: {lastMessage.type} at {lastMessage.timestamp}
        </div>
      )}
    </div>
  );
}

// ── Example 4: Manual Cache Management ─────────────────────────────────────

function CacheStatsDisplay() {
  const [stats, setStats] = React.useState(cacheManager.getCacheStats());

  React.useEffect(() => {
    const interval = setInterval(() => {
      setStats(cacheManager.getCacheStats());
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <h3>Cache Statistics</h3>
      <p>Total Requests: {stats.totalRequests}</p>
      <p>Cache Hits: {stats.cacheHits}</p>
      <p>Cache Misses: {stats.cacheMisses}</p>
      <p>Hit Rate: {(stats.hitRate * 100).toFixed(1)}%</p>
      <p>Cached Entries: {cacheManager.size()}</p>
      
      <button onClick={() => cacheManager.clear()}>
        Clear Cache
      </button>
    </div>
  );
}

// ── Example 5: Manual Cache Invalidation ───────────────────────────────────

function AdminPanel() {
  const handleInvalidateAnomalies = () => {
    cacheManager.invalidatePattern(/\/api\/anomalies/);
    console.log('Invalidated all anomaly caches');
  };

  const handleInvalidateAll = () => {
    cacheManager.clear();
    console.log('Cleared all caches');
  };

  const handleInvalidateSpecific = () => {
    cacheManager.invalidate('http://localhost:8000/api/savings/summary');
    console.log('Invalidated savings summary cache');
  };

  return (
    <div>
      <h3>Cache Management</h3>
      <button onClick={handleInvalidateAnomalies}>
        Invalidate Anomaly Caches
      </button>
      <button onClick={handleInvalidateSpecific}>
        Invalidate Savings Cache
      </button>
      <button onClick={handleInvalidateAll}>
        Clear All Caches
      </button>
    </div>
  );
}

// ── Example 6: Conditional Fetching ────────────────────────────────────────

function ConditionalFetch() {
  const [enabled, setEnabled] = React.useState(false);

  const { data, loading } = useCachedFetch<{ message: string }>(
    'http://localhost:8000/api/test',
    {
      enabled, // Only fetch when enabled is true
    }
  );

  return (
    <div>
      <button onClick={() => setEnabled(!enabled)}>
        {enabled ? 'Disable' : 'Enable'} Fetching
      </button>
      {loading && <p>Loading...</p>}
      {data && <p>Message: {data.message}</p>}
    </div>
  );
}

// ── Complete Dashboard Example ──────────────────────────────────────────────

export default function CompleteDashboard() {
  return (
    <div style={{ padding: '20px' }}>
      <h1>Cost Intelligence Dashboard</h1>
      
      <Dashboard />
      
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginTop: '20px' }}>
        <SavingsCounter />
        <AnomalyFeed />
        <CacheStatsDisplay />
        <AdminPanel />
      </div>
    </div>
  );
}
