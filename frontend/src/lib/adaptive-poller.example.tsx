/**
 * Adaptive Poller Examples
 * 
 * Demonstrates various usage patterns for the adaptive polling system.
 */

import React, { useEffect } from 'react';
import { useAdaptivePolling } from './adaptive-poller';
import { useWebSocket } from './websocket-client';

// Example 1: Basic Adaptive Polling
export function BasicAdaptivePollingExample() {
  const { data, loading, error } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/data');
      if (!response.ok) throw new Error('Failed to fetch');
      return response.json();
    },
    {
      initialInterval: 10000, // Start at 10 seconds
      minInterval: 5000,      // Minimum 5 seconds
      maxInterval: 60000,     // Maximum 60 seconds
    }
  );

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h2>Data</h2>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

// Example 2: Adaptive Polling with WebSocket Fallback
export function SavingsCounterWithAdaptivePolling() {
  const { isConnected } = useWebSocket('ws://localhost:8000/ws/dashboard');
  
  const { data: savings, isPaused, pause, resume } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/savings/summary');
      return response.json();
    },
    {
      initialInterval: 10000,
      minInterval: 5000,
      maxInterval: 60000,
    }
  );

  // Pause polling when WebSocket is connected
  useEffect(() => {
    if (isConnected) {
      pause();
    } else {
      resume();
    }
  }, [isConnected, pause, resume]);

  return (
    <div className="savings-counter">
      <div className="status">
        {isConnected ? '🟢 Real-time' : isPaused ? '⏸️ Paused' : '🔄 Polling'}
      </div>
      <h2>Total Savings This Month</h2>
      <p className="amount">${savings?.total_savings_this_month || 0}</p>
      <p className="actions">Actions Taken: {savings?.actions_taken_count || 0}</p>
    </div>
  );
}

// Example 3: Custom Data Comparison
export function AnomalyFeedWithCustomComparison() {
  const { data: anomalies, loading } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/anomalies/?limit=10');
      return response.json();
    },
    {
      initialInterval: 15000,
      minInterval: 5000,
      maxInterval: 60000,
      // Custom comparison: compare by IDs and timestamps
      compareData: (prev, current) => {
        if (!Array.isArray(prev) || !Array.isArray(current)) return false;
        if (prev.length !== current.length) return false;
        
        return prev.every((p, i) => 
          p.id === current[i].id && 
          p.detected_at === current[i].detected_at
        );
      },
    }
  );

  return (
    <div className="anomaly-feed">
      <h2>Recent Anomalies</h2>
      {loading && <div>Loading...</div>}
      {anomalies?.map((anomaly: any) => (
        <div key={anomaly.id} className="anomaly-item">
          <h3>{anomaly.description}</h3>
          <p>Detected: {new Date(anomaly.detected_at).toLocaleString()}</p>
          <p>Severity: {anomaly.severity}</p>
        </div>
      ))}
    </div>
  );
}

// Example 4: Fixed Interval (No Adaptation)
export function ModelStatusWithFixedInterval() {
  // Fixed 30-second interval by setting min = max = initial
  const { data: status } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/system/status');
      return response.json();
    },
    {
      initialInterval: 30000,
      minInterval: 30000,  // Same as initial
      maxInterval: 30000,  // Same as initial
    }
  );

  return (
    <div className="model-status">
      <h2>Model Status</h2>
      <div className={`status-indicator ${status?.state}`}>
        {status?.state || 'Unknown'}
      </div>
      <p>Last Updated: {status?.last_updated}</p>
    </div>
  );
}

// Example 5: Manual Control
export function ManualControlExample() {
  const { data, loading, isPaused, pause, resume, refetch } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/data');
      return response.json();
    },
    {
      initialInterval: 10000,
    }
  );

  return (
    <div>
      <div className="controls">
        <button onClick={pause} disabled={isPaused}>
          Pause Polling
        </button>
        <button onClick={resume} disabled={!isPaused}>
          Resume Polling
        </button>
        <button onClick={refetch} disabled={loading}>
          Refresh Now
        </button>
      </div>
      
      <div className="status">
        Status: {isPaused ? 'Paused' : loading ? 'Loading...' : 'Active'}
      </div>
      
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

// Example 6: Conditional Polling
export function ConditionalPollingExample() {
  const [shouldPoll, setShouldPoll] = React.useState(true);

  const { data } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/data');
      return response.json();
    },
    {
      initialInterval: 10000,
      enabled: shouldPoll, // Only poll when enabled
    }
  );

  return (
    <div>
      <label>
        <input
          type="checkbox"
          checked={shouldPoll}
          onChange={(e) => setShouldPoll(e.target.checked)}
        />
        Enable Polling
      </label>
      
      {data && <pre>{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

// Example 7: Action Log with Adaptive Polling
export function ActionLogWithAdaptivePolling() {
  const { isConnected, lastMessage } = useWebSocket('ws://localhost:8000/ws/dashboard');
  
  const { data: actions, pause, resume, refetch } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/actions/?limit=10');
      return response.json();
    },
    {
      initialInterval: 15000,
      minInterval: 5000,
      maxInterval: 60000,
    }
  );

  // Pause polling when WebSocket connected
  useEffect(() => {
    if (isConnected) {
      pause();
    } else {
      resume();
    }
  }, [isConnected, pause, resume]);

  // Refetch when action_executed event received
  useEffect(() => {
    if (lastMessage?.type === 'action_executed') {
      refetch();
    }
  }, [lastMessage, refetch]);

  return (
    <div className="action-log">
      <h2>Recent Actions</h2>
      <div className="connection-status">
        {isConnected ? '🟢 Real-time updates' : '🔄 Polling for updates'}
      </div>
      {actions?.map((action: any) => (
        <div key={action.id} className="action-item">
          <h3>{action.action_type}</h3>
          <p>{action.description}</p>
          <p>Executed: {new Date(action.executed_at).toLocaleString()}</p>
        </div>
      ))}
    </div>
  );
}

// Example 8: Approval Queue with Adaptive Polling
export function ApprovalQueueWithAdaptivePolling() {
  const { isConnected } = useWebSocket('ws://localhost:8000/ws/dashboard');
  
  const { data: approvals, isPaused, pause, resume } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/approvals/pending');
      return response.json();
    },
    {
      initialInterval: 10000,
      minInterval: 5000,
      maxInterval: 60000,
      // Custom comparison for approval queue
      compareData: (prev, current) => {
        if (!Array.isArray(prev) || !Array.isArray(current)) return false;
        if (prev.length !== current.length) return false;
        
        // Compare by approval IDs and status
        return prev.every((p, i) => 
          p.id === current[i].id && 
          p.status === current[i].status
        );
      },
    }
  );

  useEffect(() => {
    if (isConnected) {
      pause();
    } else {
      resume();
    }
  }, [isConnected, pause, resume]);

  return (
    <div className="approval-queue">
      <h2>Pending Approvals ({approvals?.length || 0})</h2>
      <div className="status">
        {isConnected ? '🟢 Real-time' : isPaused ? '⏸️ Paused' : '🔄 Polling'}
      </div>
      {approvals?.map((approval: any) => (
        <div key={approval.id} className="approval-item">
          <h3>{approval.action_type}</h3>
          <p>{approval.description}</p>
          <p>Requested: {new Date(approval.created_at).toLocaleString()}</p>
          <div className="actions">
            <button>Approve</button>
            <button>Reject</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// Example 9: Audit Log with Adaptive Polling (No WebSocket)
export function AuditLogWithAdaptivePolling() {
  const { data: auditLogs, loading, error } = useAdaptivePolling(
    async () => {
      const response = await fetch('/api/audit/?limit=20');
      return response.json();
    },
    {
      initialInterval: 20000, // 20 seconds
      minInterval: 10000,     // 10 seconds when active
      maxInterval: 60000,     // 60 seconds when stable
    }
  );

  return (
    <div className="audit-log">
      <h2>Audit Log</h2>
      {loading && <div>Loading...</div>}
      {error && <div>Error: {error.message}</div>}
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>User</th>
            <th>Action</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {auditLogs?.map((log: any) => (
            <tr key={log.id}>
              <td>{new Date(log.timestamp).toLocaleString()}</td>
              <td>{log.user_email}</td>
              <td>{log.action}</td>
              <td>{log.details}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
