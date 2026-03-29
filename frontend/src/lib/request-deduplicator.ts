/**
 * Request deduplicator for preventing duplicate simultaneous requests.
 * 
 * Tracks in-flight requests by endpoint and parameters, shares responses
 * with multiple callers, and implements timeout for stale requests.
 * 
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 */

// ── Types ───────────────────────────────────────────────────────────────────

interface InFlightRequest<T> {
  promise: Promise<T>;
  timestamp: number;
  abortController: AbortController;
}

// ── Request Deduplicator ────────────────────────────────────────────────────

export class RequestDeduplicator {
  private inFlightRequests: Map<string, InFlightRequest<unknown>> = new Map();
  private readonly REQUEST_TIMEOUT = 30000; // 30 seconds

  /**
   * Fetch data with request deduplication.
   * 
   * If an identical request is already in-flight, returns the existing promise
   * instead of making a new HTTP request. Shares the response with all callers.
   * 
   * Requirements: 4.1, 4.2, 4.3, 4.5
   * 
   * @param url - The URL to fetch
   * @param options - Fetch options
   * @returns Parsed response data
   */
  async fetch<T>(url: string, options: RequestInit = {}): Promise<T> {
    // Generate unique key for this request
    const requestKey = this.getRequestKey(url, options);

    // Check if request is already in-flight
    if (this.isRequestInFlight(requestKey)) {
      console.log(`[RequestDeduplicator] Reusing in-flight request for ${requestKey}`);
      const inFlight = this.inFlightRequests.get(requestKey);
      return inFlight!.promise as Promise<T>;
    }

    // Create new request with timeout
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => {
      abortController.abort();
      console.warn(`[RequestDeduplicator] Request timeout for ${requestKey}`);
    }, this.REQUEST_TIMEOUT);

    // Create the fetch promise
    const fetchPromise = fetch(url, {
      ...options,
      signal: abortController.signal,
    })
      .then(async (response) => {
        clearTimeout(timeoutId);

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        return data as T;
      })
      .catch((error) => {
        clearTimeout(timeoutId);
        
        // Handle abort/timeout
        if (error.name === 'AbortError') {
          throw new Error(`Request timeout after ${this.REQUEST_TIMEOUT}ms`);
        }
        
        throw error;
      })
      .finally(() => {
        // Cleanup: Remove from in-flight map on completion (success or failure)
        // Requirements: 4.4
        this.inFlightRequests.delete(requestKey);
        console.log(`[RequestDeduplicator] Cleaned up request ${requestKey}`);
      });

    // Store in-flight request
    this.inFlightRequests.set(requestKey, {
      promise: fetchPromise,
      timestamp: Date.now(),
      abortController,
    });

    console.log(`[RequestDeduplicator] Started new request for ${requestKey}`);
    return fetchPromise;
  }

  /**
   * Generate a unique key for a request based on URL, method, and body.
   * 
   * Format: `${method}:${url}:${bodyHash}`
   * 
   * Requirements: 4.1
   * 
   * @param url - The request URL
   * @param options - Fetch options
   * @returns Unique request key
   */
  private getRequestKey(url: string, options: RequestInit = {}): string {
    const method = (options.method || 'GET').toUpperCase();
    const bodyHash = this.hashBody(options.body);
    
    return `${method}:${url}:${bodyHash}`;
  }

  /**
   * Check if a request with the given key is currently in-flight.
   * 
   * Requirements: 4.1
   * 
   * @param key - The request key
   * @returns True if request is in-flight
   */
  private isRequestInFlight(key: string): boolean {
    return this.inFlightRequests.has(key);
  }

  /**
   * Generate a simple hash of the request body for deduplication.
   * 
   * @param body - The request body
   * @returns Hash string
   */
  private hashBody(body: BodyInit | null | undefined): string {
    if (!body) {
      return 'no-body';
    }

    // Convert body to string for hashing
    let bodyString: string;
    
    if (typeof body === 'string') {
      bodyString = body;
    } else if (body instanceof FormData) {
      // FormData is not easily hashable, use a placeholder
      bodyString = 'formdata';
    } else if (body instanceof URLSearchParams) {
      bodyString = body.toString();
    } else if (body instanceof Blob) {
      // Blob is not easily hashable, use size as identifier
      bodyString = `blob-${body.size}`;
    } else if (ArrayBuffer.isView(body)) {
      // TypedArray or DataView
      bodyString = `arraybuffer-${body.byteLength}`;
    } else if (body instanceof ArrayBuffer) {
      bodyString = `arraybuffer-${body.byteLength}`;
    } else {
      bodyString = String(body);
    }

    // Simple hash function (djb2)
    let hash = 5381;
    for (let i = 0; i < bodyString.length; i++) {
      hash = ((hash << 5) + hash) + bodyString.charCodeAt(i);
      hash = hash & hash; // Convert to 32-bit integer
    }
    
    return hash.toString(36);
  }

  /**
   * Get the number of in-flight requests.
   * 
   * @returns Number of in-flight requests
   */
  getInFlightCount(): number {
    return this.inFlightRequests.size;
  }

  /**
   * Clear all in-flight requests (aborts them).
   * 
   * Useful for cleanup or testing.
   */
  clear(): void {
    // Abort all in-flight requests
    for (const [key, request] of this.inFlightRequests) {
      request.abortController.abort();
      console.log(`[RequestDeduplicator] Aborted request ${key}`);
    }
    
    this.inFlightRequests.clear();
    console.log('[RequestDeduplicator] Cleared all in-flight requests');
  }

  /**
   * Clean up stale requests that have exceeded the timeout.
   * 
   * This is a safety mechanism in case the timeout doesn't fire properly.
   * Should be called periodically if needed.
   */
  cleanupStaleRequests(): void {
    const now = Date.now();
    let cleanedCount = 0;

    for (const [key, request] of this.inFlightRequests) {
      if (now - request.timestamp > this.REQUEST_TIMEOUT) {
        request.abortController.abort();
        this.inFlightRequests.delete(key);
        cleanedCount++;
        console.warn(`[RequestDeduplicator] Cleaned up stale request ${key}`);
      }
    }

    if (cleanedCount > 0) {
      console.log(`[RequestDeduplicator] Cleaned up ${cleanedCount} stale requests`);
    }
  }
}

// Singleton instance for global use
export const deduplicator = new RequestDeduplicator();
