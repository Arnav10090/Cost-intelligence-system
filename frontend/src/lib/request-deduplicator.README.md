# Request Deduplicator

Request deduplication for preventing duplicate simultaneous HTTP requests in the Cost Intelligence frontend.

## Overview

The Request Deduplicator prevents duplicate simultaneous requests by tracking in-flight requests and sharing responses with multiple callers. It automatically handles:

- **In-Flight Tracking**: Tracks active requests by endpoint, method, and parameters
- **Promise Sharing**: Multiple callers requesting the same endpoint receive the same promise
- **Automatic Cleanup**: Removes completed requests from tracking (success or failure)
- **Timeout Protection**: Aborts requests that exceed 30 seconds
- **Request Key Generation**: Creates unique keys based on URL, method, and body hash

## Requirements

Implements requirements 4.1, 4.2, 4.3, 4.4, 4.5 from the API Call Optimization spec.

## Usage

### Basic Usage

```tsx
import { deduplicator } from '@/lib/request-deduplicator';

async function fetchSavings() {
  try {
    const data = await deduplicator.fetch<SavingsSummary>(
      'http://localhost:8000/api/savings/summary'
    );
    console.log('Savings:', data);
  } catch (error) {
    console.error('Fetch failed:', error);
  }
}
```

### Multiple Components Requesting Same Data

```tsx
// Component A
function SavingsCounter() {
  const [data, setData] = useState(null);

  useEffect(() => {
    // This request will be made
    deduplicator.fetch('http://localhost:8000/api/savings/summary')
      .then(setData);
  }, []);

  return <div>Savings: ${data?.total_savings_this_month}</div>;
}

// Component B (mounted at same time)
function SavingsChart() {
  const [data, setData] = useState(null);

  useEffect(() => {
    // This request will REUSE the in-flight request from Component A
    // Only ONE HTTP request is made, both components get the same response
    deduplicator.fetch('http://localhost:8000/api/savings/summary')
      .then(setData);
  }, []);

  return <div>Chart for {data?.total_savings_this_month}</div>;
}
```

### With POST Requests

```tsx
import { deduplicator } from '@/lib/request-deduplicator';

async function createAnomaly(anomalyData: AnomalyInput) {
  const data = await deduplicator.fetch<Anomaly>(
    'http://localhost:8000/api/anomalies/',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(anomalyData),
    }
  );
  return data;
}
```

### Integration with Cache Manager

```tsx
import { deduplicator } from '@/lib/request-deduplicator';
import { cacheManager } from '@/lib/cache-manager';

// Combine deduplication with caching for maximum efficiency
async function fetchWithOptimizations<T>(url: string): Promise<T> {
  // First layer: Check if request is already in-flight
  // Second layer: Check if we have cached data (ETag)
  return deduplicator.fetch(url, {
    // Cache manager will add If-None-Match header if ETag exists
  });
}

// Or use cache manager's fetch which internally could use deduplicator
const data = await cacheManager.fetch<SavingsSummary>(
  'http://localhost:8000/api/savings/summary'
);
```

## API Reference

### `RequestDeduplicator`

Main class for request deduplication.

#### Methods

- **`fetch<T>(url: string, options?: RequestInit): Promise<T>`**
  - Fetch data with automatic deduplication
  - If identical request is in-flight, returns existing promise
  - Otherwise, creates new request and tracks it
  - Automatically cleans up on completion (success or failure)
  - Implements 30-second timeout

- **`getInFlightCount(): number`**
  - Get the number of currently in-flight requests
  - Useful for debugging and monitoring

- **`clear(): void`**
  - Abort all in-flight requests and clear tracking
  - Useful for cleanup or testing

- **`cleanupStaleRequests(): void`**
  - Manually clean up requests that exceeded timeout
  - Safety mechanism (timeout should handle this automatically)

### Singleton Instance

```tsx
import { deduplicator } from '@/lib/request-deduplicator';

// Use the singleton instance for global deduplication
const data = await deduplicator.fetch('/api/endpoint');
```

## How It Works

### Request Key Generation

Each request is identified by a unique key:

```
Format: ${method}:${url}:${bodyHash}

Examples:
- GET:http://localhost:8000/api/savings/summary:no-body
- POST:http://localhost:8000/api/anomalies/:elsk9l
- GET:http://localhost:8000/api/actions/?status=pending:no-body
```

The body hash is generated using a simple hash function (djb2) to create a compact identifier.

### Deduplication Flow

#### Scenario 1: Simultaneous Identical Requests (Deduplicated)

```
Time 0ms:  Component A calls fetch('/api/savings')
           → New request created, stored in in-flight map
           → HTTP request sent to server

Time 5ms:  Component B calls fetch('/api/savings')
           → Request key matches in-flight request
           → Returns existing promise (NO new HTTP request)

Time 10ms: Component C calls fetch('/api/savings')
           → Request key matches in-flight request
           → Returns existing promise (NO new HTTP request)

Time 200ms: Server responds
           → All three components receive the same response
           → Request removed from in-flight map
           → Cleanup complete

Result: 1 HTTP request instead of 3 (67% reduction)
```

#### Scenario 2: Different Requests (Not Deduplicated)

```
Time 0ms:  Component A calls fetch('/api/savings')
           → New request created (key: GET:/api/savings:no-body)

Time 5ms:  Component B calls fetch('/api/anomalies')
           → Different URL, new request created (key: GET:/api/anomalies:no-body)

Result: 2 HTTP requests (as expected, different endpoints)
```

#### Scenario 3: Sequential Requests (Not Deduplicated)

```
Time 0ms:   Component A calls fetch('/api/savings')
            → New request created

Time 200ms: Server responds, request completes
            → Request removed from in-flight map

Time 300ms: Component A calls fetch('/api/savings') again
            → No in-flight request found (previous completed)
            → New request created

Result: 2 HTTP requests (as expected, sequential)
```

### Cleanup on Completion

```typescript
// Automatic cleanup happens in finally block
fetchPromise
  .then(handleSuccess)
  .catch(handleError)
  .finally(() => {
    // Remove from in-flight map (Requirements 4.4)
    this.inFlightRequests.delete(requestKey);
  });
```

Cleanup occurs for:
- ✅ Successful responses (200, 201, etc.)
- ✅ Error responses (404, 500, etc.)
- ✅ Network errors
- ✅ Timeout errors
- ✅ Aborted requests

### Timeout Protection

```typescript
// 30-second timeout (Requirements 4.5)
const timeoutId = setTimeout(() => {
  abortController.abort();
  console.warn('Request timeout');
}, 30000);

// Cleanup timeout on completion
fetchPromise.finally(() => {
  clearTimeout(timeoutId);
});
```

## Performance Benefits

### Before Deduplication

```
Dashboard mounts with 6 components
Each component fetches /api/dashboard/summary
Result: 6 simultaneous HTTP requests to same endpoint
```

### After Deduplication

```
Dashboard mounts with 6 components
Each component calls deduplicator.fetch('/api/dashboard/summary')
Result: 1 HTTP request, response shared with all 6 components
Reduction: 83% fewer requests
```

### Real-World Impact

| Scenario | Without Dedup | With Dedup | Reduction |
|----------|---------------|------------|-----------|
| 3 components, same endpoint | 3 requests | 1 request | 67% |
| 6 components, same endpoint | 6 requests | 1 request | 83% |
| 10 components, same endpoint | 10 requests | 1 request | 90% |

## Edge Cases Handled

### 1. Request Timeout

```typescript
// Request exceeds 30 seconds
await deduplicator.fetch('/api/slow-endpoint');
// Throws: "Request timeout after 30000ms"
// Cleanup: Request removed from in-flight map
```

### 2. Request Failure

```typescript
// Server returns 500 error
try {
  await deduplicator.fetch('/api/error-endpoint');
} catch (error) {
  // All waiting callers receive the same error
  console.error(error); // "HTTP 500: Internal Server Error"
}
// Cleanup: Request removed from in-flight map
```

### 3. Network Error

```typescript
// Network connection lost
try {
  await deduplicator.fetch('/api/endpoint');
} catch (error) {
  // All waiting callers receive the same error
  console.error(error); // Network error
}
// Cleanup: Request removed from in-flight map
```

### 4. Different Request Bodies

```typescript
// Request 1
deduplicator.fetch('/api/anomalies/', {
  method: 'POST',
  body: JSON.stringify({ id: 1 })
});

// Request 2 (different body)
deduplicator.fetch('/api/anomalies/', {
  method: 'POST',
  body: JSON.stringify({ id: 2 })
});

// Result: 2 separate requests (different body hashes)
```

## Monitoring and Debugging

### Check In-Flight Requests

```typescript
import { deduplicator } from '@/lib/request-deduplicator';

// Check how many requests are currently in-flight
console.log('In-flight requests:', deduplicator.getInFlightCount());

// During simultaneous requests
const promise1 = deduplicator.fetch('/api/savings');
const promise2 = deduplicator.fetch('/api/savings');
console.log('In-flight:', deduplicator.getInFlightCount()); // 1

await Promise.all([promise1, promise2]);
console.log('In-flight:', deduplicator.getInFlightCount()); // 0
```

### Console Logging

The deduplicator logs key events:

```
[RequestDeduplicator] Started new request for GET:/api/savings:no-body
[RequestDeduplicator] Reusing in-flight request for GET:/api/savings:no-body
[RequestDeduplicator] Cleaned up request GET:/api/savings:no-body
```

## Testing

To test the request deduplicator:

```bash
# Run the manual test script
cd cost-intelligence/frontend
node test-request-deduplicator.js
```

The test script verifies:
1. ✅ Single request handling
2. ✅ Duplicate request deduplication
3. ✅ Different URLs handled separately
4. ✅ Different methods handled separately
5. ✅ Sequential requests not deduplicated
6. ✅ Request key generation
7. ✅ Cleanup on error
8. ✅ Multiple callers share same request

## Integration Examples

### Example 1: Dashboard with Multiple Components

```tsx
function Dashboard() {
  return (
    <div>
      <SavingsCounter />    {/* Calls deduplicator.fetch('/api/savings') */}
      <SavingsChart />      {/* Calls deduplicator.fetch('/api/savings') */}
      <SavingsHistory />    {/* Calls deduplicator.fetch('/api/savings') */}
    </div>
  );
}

// Result: Only 1 HTTP request made, all 3 components get the data
```

### Example 2: With React Hook

```tsx
function useDedupedFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    deduplicator.fetch<T>(url)
      .then(setData)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [url]);

  return { data, loading, error };
}

// Usage
function MyComponent() {
  const { data, loading, error } = useDedupedFetch<SavingsSummary>(
    '/api/savings/summary'
  );
  
  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;
  return <div>Savings: ${data?.total_savings_this_month}</div>;
}
```

### Example 3: Combined with Cache Manager

```tsx
// Create a wrapper that combines both optimizations
async function optimizedFetch<T>(url: string, options?: RequestInit): Promise<T> {
  // Deduplication prevents simultaneous duplicate requests
  return deduplicator.fetch(url, {
    ...options,
    // Cache manager logic could be integrated here
  });
}

// Or integrate at the cache manager level
class OptimizedCacheManager extends CacheManager {
  async fetch<T>(url: string, options?: RequestInit): Promise<T> {
    // Use deduplicator for the actual fetch
    return deduplicator.fetch(url, {
      ...options,
      headers: this.addCacheHeaders(url, options?.headers),
    });
  }
}
```

## Notes

- **In-flight tracking is in-memory**: Cleared on page reload
- **Request keys are case-sensitive**: `GET` and `get` are different
- **Body hashing is simple**: Uses djb2 algorithm for speed
- **Timeout is fixed**: 30 seconds (not configurable)
- **Singleton instance recommended**: Use `deduplicator` for global deduplication
- **Cleanup is automatic**: No manual cleanup needed in normal usage
- **Works with all HTTP methods**: GET, POST, PUT, DELETE, PATCH, etc.

## Comparison with Cache Manager

| Feature | Request Deduplicator | Cache Manager |
|---------|---------------------|---------------|
| **Purpose** | Prevent duplicate simultaneous requests | Reduce redundant data transfer |
| **Scope** | In-flight requests only | Completed requests |
| **Duration** | Milliseconds (request duration) | Minutes/hours (until invalidated) |
| **Storage** | In-flight map | Cache map with ETags |
| **Benefit** | Reduces concurrent load | Reduces bandwidth and latency |
| **Use Case** | Multiple components mounting simultaneously | Repeated requests over time |

**Best Practice**: Use both together for maximum optimization!

