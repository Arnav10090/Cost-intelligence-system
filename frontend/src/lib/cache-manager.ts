/**
 * Cache manager for HTTP caching with ETag support.
 * 
 * Provides ETag storage, conditional requests with If-None-Match headers,
 * and 304 response handling with cached data return.
 * 
 * Requirements: 2.4, 2.5, 2.6, 2.7
 */

// ── Types ───────────────────────────────────────────────────────────────────

export interface CacheEntry {
  etag: string;
  data: unknown;
  timestamp: number;
  url: string;
}

export interface CacheStats {
  hitRate: number;
  totalRequests: number;
  cacheHits: number;
  cacheMisses: number;
}

// ── Cache Manager ───────────────────────────────────────────────────────────

export class CacheManager {
  private cache: Map<string, CacheEntry> = new Map();
  private stats = {
    totalRequests: 0,
    cacheHits: 0,
    cacheMisses: 0,
  };

  /**
   * Fetch data with ETag-based caching.
   * 
   * Automatically adds If-None-Match headers for cached endpoints
   * and handles 304 Not Modified responses by returning cached data.
   * 
   * Requirements: 2.4, 2.5, 2.6
   * 
   * @param url - The URL to fetch
   * @param options - Fetch options
   * @returns Parsed response data
   */
  async fetch<T>(url: string, options: RequestInit = {}): Promise<T> {
    this.stats.totalRequests++;

    // Get cached entry if exists
    const cachedEntry = this.cache.get(url);
    
    // Add If-None-Match header if we have a cached ETag
    const headers = new Headers(options.headers);
    if (cachedEntry) {
      headers.set('If-None-Match', cachedEntry.etag);
    }

    // Make request with conditional headers
    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Handle 304 Not Modified - return cached data
    if (response.status === 304) {
      if (!cachedEntry) {
        throw new Error('Received 304 but no cached data available');
      }
      
      this.stats.cacheHits++;
      console.log(`[CacheManager] Cache hit for ${url}`);
      return cachedEntry.data as T;
    }

    // Handle error responses
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    // Parse response data
    const data = await response.json();
    this.stats.cacheMisses++;

    // Store ETag if present in response (Requirements 9.4 - graceful degradation)
    // If ETag is not present, process response normally without caching
    const etag = response.headers.get('ETag');
    if (etag) {
      this.cache.set(url, {
        etag,
        data,
        timestamp: Date.now(),
        url,
      });
      console.log(`[CacheManager] Cached ${url} with ETag ${etag}`);
    }

    return data as T;
  }

  /**
   * Invalidate cache for a specific URL.
   * 
   * Requirements: 2.7
   * 
   * @param url - The URL to invalidate
   */
  invalidate(url: string): void {
    const deleted = this.cache.delete(url);
    if (deleted) {
      console.log(`[CacheManager] Invalidated cache for ${url}`);
    }
  }

  /**
   * Manually set a cache entry.
   * 
   * This is useful for pre-populating the cache with data from aggregated endpoints.
   * 
   * @param url - The URL to cache
   * @param data - The data to cache
   * @param etag - The ETag for the cached data
   */
  setCacheEntry(url: string, data: unknown, etag: string): void {
    this.cache.set(url, {
      etag,
      data,
      timestamp: Date.now(),
      url,
    });
    console.log(`[CacheManager] Manually cached ${url} with ETag ${etag}`);
  }

  /**
   * Invalidate cache entries matching a pattern.
   * 
   * Requirements: 2.7
   * 
   * @param pattern - RegExp pattern to match URLs
   */
  invalidatePattern(pattern: RegExp): void {
    let invalidatedCount = 0;
    
    for (const [url] of this.cache) {
      if (pattern.test(url)) {
        this.cache.delete(url);
        invalidatedCount++;
      }
    }

    if (invalidatedCount > 0) {
      console.log(`[CacheManager] Invalidated ${invalidatedCount} cache entries matching pattern ${pattern}`);
    }
  }

  /**
   * Get cache statistics.
   * 
   * @returns Cache hit rate and request counts
   */
  getCacheStats(): CacheStats {
    const hitRate = this.stats.totalRequests > 0
      ? this.stats.cacheHits / this.stats.totalRequests
      : 0;

    return {
      hitRate,
      totalRequests: this.stats.totalRequests,
      cacheHits: this.stats.cacheHits,
      cacheMisses: this.stats.cacheMisses,
    };
  }

  /**
   * Clear all cached entries.
   */
  clear(): void {
    this.cache.clear();
    console.log('[CacheManager] Cache cleared');
  }

  /**
   * Get the number of cached entries.
   */
  size(): number {
    return this.cache.size;
  }

  /**
   * Invalidate cache based on WebSocket message type.
   * 
   * This method should be called when WebSocket updates are received
   * to ensure cached data is refreshed on the next request.
   * 
   * Requirements: 2.7
   * 
   * @param messageType - The WebSocket message type
   */
  invalidateByMessageType(messageType: string): void {
    switch (messageType) {
      case 'anomaly_created':
        // Invalidate anomaly-related endpoints
        this.invalidatePattern(/\/api\/anomalies/);
        this.invalidatePattern(/\/api\/dashboard\/summary/);
        break;
      
      case 'action_executed':
        // Invalidate action-related endpoints
        this.invalidatePattern(/\/api\/actions/);
        this.invalidatePattern(/\/api\/dashboard\/summary/);
        break;
      
      case 'approval_pending':
      case 'approval_status_changed':
        // Invalidate approval-related endpoints
        this.invalidatePattern(/\/api\/approvals/);
        this.invalidatePattern(/\/api\/dashboard\/summary/);
        break;
      
      case 'savings_updated':
        // Invalidate savings-related endpoints
        this.invalidatePattern(/\/api\/savings/);
        this.invalidatePattern(/\/api\/dashboard\/summary/);
        break;
      
      case 'system_status_changed':
        // Invalidate system status endpoints
        this.invalidatePattern(/\/api\/system\/status/);
        this.invalidatePattern(/\/api\/dashboard\/summary/);
        break;
      
      default:
        console.warn(`[CacheManager] Unknown message type for cache invalidation: ${messageType}`);
    }
  }
}

// Singleton instance for global use
export const cacheManager = new CacheManager();


// ── React Hook ──────────────────────────────────────────────────────────────

import { useEffect, useState, useCallback, useRef } from 'react';

export interface UseCachedFetchOptions {
  /** Whether to fetch immediately on mount (default: true) */
  enabled?: boolean;
  /** Polling interval in milliseconds (0 to disable) */
  pollingInterval?: number;
  /** Custom cache manager instance (default: singleton) */
  cacheManager?: CacheManager;
}

export interface UseCachedFetchResult<T> {
  /** Fetched data */
  data: T | null;
  /** Whether a request is in progress */
  loading: boolean;
  /** Error if request failed */
  error: Error | null;
  /** Manually trigger a refetch */
  refetch: () => Promise<void>;
}

/**
 * React hook for cached data fetching with ETag support.
 * 
 * Integrates with CacheManager to provide automatic caching,
 * conditional requests, and 304 response handling.
 * 
 * Requirements: 2.5
 * 
 * @param url - The URL to fetch
 * @param options - Fetch and caching options
 * @returns Data, loading state, error, and refetch function
 * 
 * @example
 * ```tsx
 * function SavingsCounter() {
 *   const { data, loading, error, refetch } = useCachedFetch<SavingsSummary>(
 *     '/api/savings/summary'
 *   );
 * 
 *   if (loading) return <div>Loading...</div>;
 *   if (error) return <div>Error: {error.message}</div>;
 *   
 *   return <div>Total Savings: ${data?.total_savings_this_month}</div>;
 * }
 * ```
 */
export function useCachedFetch<T>(
  url: string,
  options: UseCachedFetchOptions = {}
): UseCachedFetchResult<T> {
  const {
    enabled = true,
    pollingInterval = 0,
    cacheManager: customCacheManager,
  } = options;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  
  const manager = customCacheManager || cacheManager;
  const pollingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isMountedRef = useRef(true);

  const fetchData = useCallback(async () => {
    if (!enabled) return;

    setLoading(true);
    setError(null);

    try {
      const result = await manager.fetch<T>(url);
      
      // Only update state if component is still mounted
      if (isMountedRef.current) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (isMountedRef.current) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        console.error(`[useCachedFetch] Error fetching ${url}:`, error);
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [url, enabled, manager]);

  // Initial fetch on mount
  useEffect(() => {
    if (enabled) {
      fetchData();
    }
  }, [enabled, fetchData]);

  // Polling interval
  useEffect(() => {
    if (!enabled || pollingInterval <= 0) {
      return;
    }

    const startPolling = () => {
      pollingTimeoutRef.current = setTimeout(() => {
        fetchData().then(() => {
          // Schedule next poll
          if (isMountedRef.current && pollingInterval > 0) {
            startPolling();
          }
        });
      }, pollingInterval);
    };

    startPolling();

    return () => {
      if (pollingTimeoutRef.current) {
        clearTimeout(pollingTimeoutRef.current);
        pollingTimeoutRef.current = null;
      }
    };
  }, [enabled, pollingInterval, fetchData]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (pollingTimeoutRef.current) {
        clearTimeout(pollingTimeoutRef.current);
      }
    };
  }, []);

  return {
    data,
    loading,
    error,
    refetch: fetchData,
  };
}



// ── WebSocket Integration ──────────────────────────────────────────────────

import { WebSocketMessage } from './websocket-client';

/**
 * Hook that integrates WebSocket updates with cache invalidation.
 * 
 * Automatically invalidates cache entries when WebSocket messages
 * indicate data has changed on the backend.
 * 
 * Requirements: 2.7
 * 
 * @param lastMessage - Last WebSocket message received
 * @param cacheManager - Cache manager instance (default: singleton)
 * 
 * @example
 * ```tsx
 * function Dashboard() {
 *   const { lastMessage } = useWebSocket('ws://localhost:8000/ws/dashboard');
 *   
 *   // Automatically invalidate cache on WebSocket updates
 *   useWebSocketCacheInvalidation(lastMessage);
 *   
 *   // Now useCachedFetch will refetch when cache is invalidated
 *   const { data } = useCachedFetch('/api/savings/summary');
 * }
 * ```
 */
export function useWebSocketCacheInvalidation(
  lastMessage: WebSocketMessage | null,
  customCacheManager?: CacheManager
): void {
  const manager = customCacheManager || cacheManager;

  useEffect(() => {
    if (lastMessage) {
      manager.invalidateByMessageType(lastMessage.type);
    }
  }, [lastMessage, manager]);
}
