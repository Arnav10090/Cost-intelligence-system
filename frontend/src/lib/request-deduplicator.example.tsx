/**
 * Example usage of RequestDeduplicator.
 * 
 * This file demonstrates how to use the request deduplicator to prevent
 * duplicate simultaneous HTTP requests and share responses with multiple callers.
 */

import React, { useEffect, useState } from 'react';
import { deduplicator } from './request-deduplicator';

// ── Example 1: Basic Deduplication ─────────────────────────────────────────

interface SavingsSummary {
  total_savings_this_month: number;
  actions_taken_count: number;
  anomalies_detected_count: number;
}

function SavingsCounter() {
  const [data, setData] = useState<SavingsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    deduplicator.fetch<SavingsSummary>('http://localhost:8000/api/savings/summary')
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div>Loading savings...</div>;
  if (error) return <div>Error: {error.message}</div>;
  if (!data) return <div>No data</div>;

  return (
    <div>
      <h3>Savings Counter</h3>
      <p>Total Savings: ${data.total_savings_this_month}</p>
    </div>
  );
}

// ── Example 2: Multiple Components, Same Endpoint ──────────────────────────

function SavingsChart() {
  const [data, setData] = useState<SavingsSummary | null>(null);

  useEffect(() => {
    // This will REUSE the in-flight request from SavingsCounter
    // if both components mount at the same time
    deduplicator.fetch<SavingsSummary>('http://localhost:8000/api/savings/summary')
      .then(setData);
  }, []);

  if (!data) return <div>Loading chart...</div>;

  return (
    <div>
      <h3>Savings Chart</h3>
      <p>Actions Taken: {data.actions_taken_count}</p>
    </div>
  );
}

function SavingsHistory() {
  const [data, setData] = useState<SavingsSummary | null>(null);

  useEffect(() => {
    // This will ALSO reuse the same in-flight request
    deduplicator.fetch<SavingsSummary>('http://localhost:8000/api/savings/summary')
      .then(setData);
  }, []);

  if (!data) return <div>Loading history...</div>;

  return (
    <div>
      <h3>Savings History</h3>
      <p>Anomalies Detected: {data.anomalies_detected_count}</p>
    </div>
  );
}

// Dashboard that mounts all three components simultaneously
function SavingsDashboard() {
  return (
    <div>
      <h2>Savings Dashboard</h2>
      <p style={{ color: 'green' }}>
        ✓ Only 1 HTTP request made for all 3 components!
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '10px' }}>
        <SavingsCounter />
        <SavingsChart />
        <SavingsHistory />
      </div>
    </div>
  );
}

// ── Example 3: Custom Hook with Deduplication ──────────────────────────────

function useDedupedFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refetch = React.useCallback(() => {
    setLoading(true);
    setError(null);
    
    deduplicator.fetch<T>(url)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [url]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}

// Usage of custom hook
function AnomalyFeed() {
  const { data, loading, error, refetch } = useDedupedFetch<Array<{ id: string; title: string }>>(
    'http://localhost:8000/api/anomalies/'
  );

  if (loading && !data) return <div>Loading anomalies...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return (
    <div>
      <h3>Recent Anomalies</h3>
      <button onClick={refetch}>Refresh</button>
      <ul>
        {data?.map((anomaly) => (
          <li key={anomaly.id}>{anomaly.title}</li>
        ))}
      </ul>
    </div>
  );
}

// ── Example 4: POST Request Deduplication ──────────────────────────────────

interface AnomalyInput {
  title: string;
  severity: string;
}

interface Anomaly extends AnomalyInput {
  id: string;
  created_at: string;
}

function CreateAnomalyForm() {
  const [title, setTitle] = useState('');
  const [severity, setSeverity] = useState('medium');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<Anomaly | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      const anomaly = await deduplicator.fetch<Anomaly>(
        'http://localhost:8000/api/anomalies/',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, severity }),
        }
      );
      setResult(anomaly);
    } catch (error) {
      console.error('Failed to create anomaly:', error);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h3>Create Anomaly</h3>
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Anomaly title"
        />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <button type="submit" disabled={submitting}>
          {submitting ? 'Creating...' : 'Create'}
        </button>
      </form>
      {result && <p>Created anomaly: {result.id}</p>}
    </div>
  );
}

// ── Example 5: Monitoring In-Flight Requests ───────────────────────────────

function DeduplicationMonitor() {
  const [inFlightCount, setInFlightCount] = useState(0);
  const [requestLog, setRequestLog] = useState<string[]>([]);

  useEffect(() => {
    const interval = setInterval(() => {
      setInFlightCount(deduplicator.getInFlightCount());
    }, 100);

    return () => clearInterval(interval);
  }, []);

  const makeRequest = async (endpoint: string) => {
    const timestamp = new Date().toLocaleTimeString();
    setRequestLog((prev) => [...prev, `${timestamp}: Started ${endpoint}`]);

    try {
      await deduplicator.fetch(`http://localhost:8000${endpoint}`);
      setRequestLog((prev) => [...prev, `${timestamp}: Completed ${endpoint}`]);
    } catch (error) {
      setRequestLog((prev) => [...prev, `${timestamp}: Failed ${endpoint}`]);
    }
  };

  const makeMultipleRequests = () => {
    // Make 5 simultaneous requests to the same endpoint
    const endpoint = '/api/savings/summary';
    for (let i = 0; i < 5; i++) {
      makeRequest(endpoint);
    }
  };

  return (
    <div>
      <h3>Deduplication Monitor</h3>
      <p>In-Flight Requests: {inFlightCount}</p>
      
      <button onClick={makeMultipleRequests}>
        Make 5 Simultaneous Requests
      </button>
      
      <button onClick={() => setRequestLog([])}>
        Clear Log
      </button>

      <div style={{ 
        maxHeight: '200px', 
        overflow: 'auto', 
        border: '1px solid #ccc', 
        padding: '10px',
        marginTop: '10px',
        fontFamily: 'monospace',
        fontSize: '12px'
      }}>
        {requestLog.map((log, i) => (
          <div key={i}>{log}</div>
        ))}
      </div>
    </div>
  );
}

// ── Example 6: Comparison - With vs Without Deduplication ──────────────────

function ComparisonDemo() {
  const [withDedup, setWithDedup] = useState(true);
  const [requestCount, setRequestCount] = useState(0);

  const makeRequestsWithDedup = async () => {
    setRequestCount(0);
    const url = 'http://localhost:8000/api/savings/summary';
    
    // All 3 requests will be deduplicated into 1
    const promises = [
      deduplicator.fetch(url).then(() => setRequestCount((c) => c + 1)),
      deduplicator.fetch(url).then(() => setRequestCount((c) => c + 1)),
      deduplicator.fetch(url).then(() => setRequestCount((c) => c + 1)),
    ];

    await Promise.all(promises);
  };

  const makeRequestsWithoutDedup = async () => {
    setRequestCount(0);
    const url = 'http://localhost:8000/api/savings/summary';
    
    // All 3 requests will be made separately
    const promises = [
      fetch(url).then(() => setRequestCount((c) => c + 1)),
      fetch(url).then(() => setRequestCount((c) => c + 1)),
      fetch(url).then(() => setRequestCount((c) => c + 1)),
    ];

    await Promise.all(promises);
  };

  return (
    <div>
      <h3>Comparison Demo</h3>
      
      <div>
        <label>
          <input
            type="radio"
            checked={withDedup}
            onChange={() => setWithDedup(true)}
          />
          With Deduplication
        </label>
        <label>
          <input
            type="radio"
            checked={!withDedup}
            onChange={() => setWithDedup(false)}
          />
          Without Deduplication
        </label>
      </div>

      <button onClick={withDedup ? makeRequestsWithDedup : makeRequestsWithoutDedup}>
        Make 3 Simultaneous Requests
      </button>

      <p>
        Expected HTTP Requests: {withDedup ? '1' : '3'}
      </p>
      <p>
        Responses Received: {requestCount}
      </p>
      <p style={{ color: withDedup ? 'green' : 'orange' }}>
        {withDedup 
          ? '✓ Only 1 HTTP request made, response shared with all callers'
          : '⚠ 3 separate HTTP requests made'}
      </p>
    </div>
  );
}

// ── Example 7: Error Handling ──────────────────────────────────────────────

function ErrorHandlingDemo() {
  const [result, setResult] = useState<string>('');

  const testSuccessfulRequest = async () => {
    try {
      const data = await deduplicator.fetch('http://localhost:8000/api/savings/summary');
      setResult(`✓ Success: ${JSON.stringify(data)}`);
    } catch (error) {
      setResult(`✗ Error: ${error}`);
    }
  };

  const testFailedRequest = async () => {
    try {
      await deduplicator.fetch('http://localhost:8000/api/nonexistent');
      setResult('✓ Success (unexpected)');
    } catch (error) {
      setResult(`✓ Error caught correctly: ${error}`);
    }
  };

  const testMultipleCallersWithError = async () => {
    setResult('Making 3 simultaneous requests to failing endpoint...');
    
    const promises = [
      deduplicator.fetch('http://localhost:8000/api/error-endpoint').catch(e => `Caller 1: ${e}`),
      deduplicator.fetch('http://localhost:8000/api/error-endpoint').catch(e => `Caller 2: ${e}`),
      deduplicator.fetch('http://localhost:8000/api/error-endpoint').catch(e => `Caller 3: ${e}`),
    ];

    const results = await Promise.all(promises);
    setResult(`All callers received error:\n${results.join('\n')}`);
  };

  return (
    <div>
      <h3>Error Handling</h3>
      
      <button onClick={testSuccessfulRequest}>
        Test Successful Request
      </button>
      
      <button onClick={testFailedRequest}>
        Test Failed Request
      </button>
      
      <button onClick={testMultipleCallersWithError}>
        Test Multiple Callers with Error
      </button>

      <pre style={{ 
        background: '#f5f5f5', 
        padding: '10px', 
        marginTop: '10px',
        whiteSpace: 'pre-wrap'
      }}>
        {result}
      </pre>
    </div>
  );
}

// ── Complete Example Dashboard ──────────────────────────────────────────────

export default function RequestDeduplicatorExamples() {
  return (
    <div style={{ padding: '20px' }}>
      <h1>Request Deduplicator Examples</h1>
      
      <div style={{ marginBottom: '40px' }}>
        <h2>Example 1: Multiple Components, Same Endpoint</h2>
        <SavingsDashboard />
      </div>

      <div style={{ marginBottom: '40px' }}>
        <h2>Example 2: Custom Hook</h2>
        <AnomalyFeed />
      </div>

      <div style={{ marginBottom: '40px' }}>
        <h2>Example 3: POST Request</h2>
        <CreateAnomalyForm />
      </div>

      <div style={{ marginBottom: '40px' }}>
        <h2>Example 4: Monitoring</h2>
        <DeduplicationMonitor />
      </div>

      <div style={{ marginBottom: '40px' }}>
        <h2>Example 5: Comparison</h2>
        <ComparisonDemo />
      </div>

      <div style={{ marginBottom: '40px' }}>
        <h2>Example 6: Error Handling</h2>
        <ErrorHandlingDemo />
      </div>
    </div>
  );
}

