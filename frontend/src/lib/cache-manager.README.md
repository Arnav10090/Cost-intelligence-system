# Cache Manager

HTTP caching with ETag support for the Cost Intelligence frontend.

## Overview

The Cache Manager implements client-side HTTP caching using ETags to reduce redundant data transfer and API calls. It automatically handles:

- **ETag Storage**: Stores ETags from server responses
- **Conditional Requests**: Adds `If-None-Match` headers to subsequent requests
- **304 Handling**: Returns cached data when server responds with 304 Not Modified
- **Cache Invalidation**: Invalidates cache entries based on WebSocket updates or manual triggers

## Requirements

Implements requirements 2.4, 2.5, 2.6, 2.7 from the API Call Optimization spec.

## Usage

### Basic Usage with React Hook

```tsx
import { useCachedFetch } from '@/lib/cache-manager';

function SavingsCounter() {
  const { data, loading, error, refetch } = useCachedFetch<SavingsSummary>(
    'http://localhost:8000/api/savings/summary'
  );

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;
  
  return (
    <div>
      <h2>Total Savings: ${data?.total_savings_this_month}</h2>
      <button onClick={refetch}>Refresh</button>
    </div>
  );
}
```

### With Polling

```tsx
const { data, loading, error } = useCachedFetch<Anomaly[]>(
  'http://localhost:8000/api/anomalies/',
  {
    pollingInterval: 15000, // Poll every 15 seconds
  }
);
```

### With WebSocket Integration

```tsx
import { useWebSocket } from '@/lib/websocket-client';
import { useCachedFetch, useWebSocketCacheInvalidation } from '@/lib/cache-manager';

function Dashboard() {
  // Connect to WebSocket
  const { isConnected, lastMessage } = useWebSocket(
    'ws://localhost:8000/ws/dashboard'
  );

  // Automatically invalidate cache on WebSocket updates
  useWebSocketCacheInvalidation(lastMessage);

  // Fetch with caching - will refetch when cache is invalidated
  const { data } = useCachedFetch<SavingsSummary>(
    'http://localhost:8000/api/savings/summary'
  );

  return <div>Savings: ${data?.total_savings_this_month}</div>;
}
```

### Manual Cache Management

```tsx
import { cacheManager } from '@/lib/cache-manager';

// Invalidate specific URL
cacheManager.invalidate('http://localhost:8000/api/savings/summary');

// Invalidate by pattern
cacheManager.invalidatePattern(/\/api\/anomalies/);

// Clear all cache
cacheManager.clear();

// Get cache statistics
const stats = cacheManager.getCacheStats();
console.log(`Hit rate: ${stats.hitRate * 100}%`);
console.log(`Total requests: ${stats.totalRequests}`);
console.log(`Cache hits: ${stats.cacheHits}`);
console.log(`Cache misses: ${stats.cacheMisses}`);
```

### Direct CacheManager Usage

```tsx
import { cacheManager } from '@/lib/cache-manager';

async function fetchData() {
  try {
    const data = await cacheManager.fetch<SavingsSummary>(
      'http://localhost:8000/api/savings/summary'
    );
    console.log('Data:', data);
  } catch (error) {
    console.error('Fetch failed:', error);
  }
}
```

## API Reference

### `CacheManager`

Main class for managing HTTP cache with ETags.

#### Methods

- **`fetch<T>(url: string, options?: RequestInit): Promise<T>`**
  - Fetch data with automatic ETag caching
  - Adds `If-None-Match` header if ETag exists
  - Returns cached data on 304 response
  - Stores new ETag on 200 response

- **`invalidate(url: string): void`**
  - Invalidate cache for a specific URL

- **`invalidatePattern(pattern: RegExp): void`**
  - Invalidate all cache entries matching a pattern

- **`invalidateByMessageType(messageType: string): void`**
  - Invalidate cache based on WebSocket message type
  - Automatically maps message types to affected endpoints

- **`getCacheStats(): CacheStats`**
  - Get cache statistics (hit rate, total requests, hits, misses)

- **`clear(): void`**
  - Clear all cached entries

- **`size(): number`**
  - Get number of cached entries

### `useCachedFetch<T>(url, options)`

React hook for cached data fetching.

#### Parameters

- **`url: string`** - The URL to fetch
- **`options?: UseCachedFetchOptions`**
  - `enabled?: boolean` - Whether to fetch immediately (default: true)
  - `pollingInterval?: number` - Polling interval in ms (0 to disable)
  - `cacheManager?: CacheManager` - Custom cache manager instance

#### Returns

- **`data: T | null`** - Fetched data
- **`loading: boolean`** - Whether a request is in progress
- **`error: Error | null`** - Error if request failed
- **`refetch: () => Promise<void>`** - Manually trigger a refetch

### `useWebSocketCacheInvalidation(lastMessage, cacheManager?)`

React hook that automatically invalidates cache when WebSocket messages arrive.

#### Parameters

- **`lastMessage: WebSocketMessage | null`** - Last WebSocket message
- **`cacheManager?: CacheManager`** - Custom cache manager instance

## Cache Invalidation Strategy

The cache manager automatically invalidates cache entries based on WebSocket message types:

| Message Type | Invalidated Endpoints |
|--------------|----------------------|
| `anomaly_created` | `/api/anomalies/*`, `/api/dashboard/summary` |
| `action_executed` | `/api/actions/*`, `/api/dashboard/summary` |
| `approval_pending` | `/api/approvals/*`, `/api/dashboard/summary` |
| `approval_status_changed` | `/api/approvals/*`, `/api/dashboard/summary` |
| `savings_updated` | `/api/savings/*`, `/api/dashboard/summary` |
| `system_status_changed` | `/api/system/status/*`, `/api/dashboard/summary` |

## How It Works

### 1. First Request (Cache Miss)

```
Client → GET /api/savings/summary
Server → 200 OK
         ETag: "abc123"
         Body: { total_savings: 1000 }

Cache Manager:
- Stores ETag "abc123" for URL
- Stores response data
- Returns data to caller
```

### 2. Second Request (Cache Hit)

```
Client → GET /api/savings/summary
         If-None-Match: "abc123"
Server → 304 Not Modified
         (no body)

Cache Manager:
- Detects 304 response
- Returns cached data
- No data transfer needed!
```

### 3. After Data Change

```
WebSocket → { type: "savings_updated", ... }

Cache Manager:
- Invalidates /api/savings/* cache
- Next request will be a cache miss
- Fresh data will be fetched
```

## Performance Benefits

- **Reduced Bandwidth**: 304 responses have no body, saving bandwidth
- **Faster Response**: Cached data returned immediately on 304
- **Lower Server Load**: Server can quickly check ETag without processing data
- **Automatic Invalidation**: WebSocket updates ensure data freshness

## Example: Complete Integration

See `cache-manager.example.tsx` for complete examples including:

1. Basic cached fetch
2. Polling with cache
3. WebSocket integration
4. Manual cache management
5. Cache statistics display
6. Conditional fetching

## Testing

To test the cache manager:

1. Start the backend server with ETag support
2. Make a request - should see cache miss
3. Make the same request - should see cache hit (304)
4. Trigger a WebSocket update - cache should be invalidated
5. Make the request again - should see cache miss (fresh data)

Check browser DevTools Network tab to see:
- First request: 200 OK with full response
- Second request: 304 Not Modified with no body
- After invalidation: 200 OK with full response

## Notes

- Cache is stored in memory (Map) and cleared on page reload
- ETags are session-scoped
- Cache invalidation is automatic with WebSocket integration
- Manual invalidation is available for custom scenarios
- Singleton instance (`cacheManager`) is provided for convenience
