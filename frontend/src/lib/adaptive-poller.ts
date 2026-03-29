/**
 * Adaptive Poller
 * 
 * Manages polling intervals based on data volatility and tab visibility.
 * Implements intelligent interval adjustment to reduce API calls while
 * maintaining responsiveness for changing data.
 * 
 * Features:
 * - Adaptive intervals (5s-60s) based on data change detection
 * - Tab visibility detection (5x interval when inactive)
 * - Pause/resume for WebSocket connection state
 * - Automatic cleanup on stop
 * 
 * Requirements: 5.1, 5.2, 5.3, 5.5, 5.6
 */

export interface AdaptivePollerOptions {
  minInterval?: number; // Minimum polling interval in ms (default: 5000)
  maxInterval?: number; // Maximum polling interval in ms (default: 60000)
  initialInterval: number; // Starting interval in ms
  compareData?: (prev: any, current: any) => boolean; // Custom comparison function
}

export class AdaptivePoller<T = any> {
  private fetchFn: () => Promise<T>;
  private options: Required<AdaptivePollerOptions>;
  private currentInterval: number;
  private unchangedCount: number = 0;
  private timerId: NodeJS.Timeout | null = null;
  private lastData: T | null = null;
  private isPaused: boolean = false;
  private isTabVisible: boolean = true;
  private visibilityHandler: (() => void) | null = null;

  constructor(
    fetchFn: () => Promise<T>,
    options: AdaptivePollerOptions
  ) {
    this.fetchFn = fetchFn;
    this.options = {
      minInterval: options.minInterval ?? 5000,
      maxInterval: options.maxInterval ?? 60000,
      initialInterval: options.initialInterval,
      compareData: options.compareData ?? this.defaultCompare,
    };
    this.currentInterval = this.options.initialInterval;
  }

  /**
   * Start polling with adaptive intervals
   */
  start(): void {
    if (this.timerId) {
      return; // Already running
    }

    this.setupVisibilityDetection();
    this.scheduleNextPoll();
  }

  /**
   * Stop polling and cleanup
   */
  stop(): void {
    if (this.timerId) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }

    this.cleanupVisibilityDetection();
    this.lastData = null;
    this.unchangedCount = 0;
  }

  /**
   * Pause polling (called when WebSocket connects)
   * Requirements: 5.1
   */
  pause(): void {
    this.isPaused = true;
    if (this.timerId) {
      clearTimeout(this.timerId);
      this.timerId = null;
    }
  }

  /**
   * Resume polling (called when WebSocket disconnects)
   * Requirements: 5.1
   */
  resume(): void {
    this.isPaused = false;
    if (!this.timerId) {
      this.scheduleNextPoll();
    }
  }

  /**
   * Get current polling state
   */
  getState(): {
    isPaused: boolean;
    currentInterval: number;
    unchangedCount: number;
  } {
    return {
      isPaused: this.isPaused,
      currentInterval: this.currentInterval,
      unchangedCount: this.unchangedCount,
    };
  }

  /**
   * Schedule the next poll with current interval
   */
  private scheduleNextPoll(): void {
    if (this.isPaused) {
      return;
    }

    const effectiveInterval = this.calculateEffectiveInterval();

    this.timerId = setTimeout(async () => {
      this.timerId = null;
      await this.executePoll();
      this.scheduleNextPoll();
    }, effectiveInterval);
  }

  /**
   * Execute a single poll and adjust interval based on result
   */
  private async executePoll(): Promise<void> {
    try {
      const data = await this.fetchFn();
      const dataChanged = this.detectDataChange(data);
      this.adjustInterval(dataChanged);
      this.lastData = data;
    } catch (error) {
      // Log error but continue polling
      console.error('[AdaptivePoller] Poll failed:', error);
    }
  }

  /**
   * Detect if data has changed since last poll
   */
  private detectDataChange(currentData: T): boolean {
    if (this.lastData === null) {
      return true; // First poll, consider as changed
    }

    return !this.options.compareData(this.lastData, currentData);
  }

  /**
   * Adjust polling interval based on data volatility
   * Requirements: 5.2, 5.3
   */
  private adjustInterval(dataChanged: boolean): void {
    if (dataChanged) {
      // Data is volatile, poll more frequently
      this.currentInterval = Math.max(
        this.options.minInterval,
        this.currentInterval * 0.5
      );
      this.unchangedCount = 0;
    } else {
      // Data is stable
      this.unchangedCount++;

      if (this.unchangedCount >= 3) {
        // Data unchanged for 3 consecutive polls, poll less frequently
        this.currentInterval = Math.min(
          this.options.maxInterval,
          this.currentInterval * 1.5
        );
      }
    }
  }

  /**
   * Calculate effective interval considering tab visibility
   * Requirements: 5.5, 5.6
   */
  private calculateEffectiveInterval(): number {
    if (this.isTabVisible) {
      return this.currentInterval;
    } else {
      // Tab inactive: 5x current interval
      return this.currentInterval * 5;
    }
  }

  /**
   * Setup Page Visibility API detection
   * Requirements: 5.5, 5.6
   */
  private setupVisibilityDetection(): void {
    if (typeof document === 'undefined' || !('hidden' in document)) {
      // Page Visibility API not supported, assume always visible
      return;
    }

    this.visibilityHandler = () => {
      const wasVisible = this.isTabVisible;
      this.isTabVisible = !document.hidden;

      if (wasVisible !== this.isTabVisible) {
        // Visibility changed, reschedule with new interval
        if (this.timerId) {
          clearTimeout(this.timerId);
          this.timerId = null;
        }
        if (!this.isPaused) {
          this.scheduleNextPoll();
        }
      }
    };

    document.addEventListener('visibilitychange', this.visibilityHandler);
  }

  /**
   * Cleanup visibility detection
   */
  private cleanupVisibilityDetection(): void {
    if (this.visibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.visibilityHandler);
      this.visibilityHandler = null;
    }
  }

  /**
   * Default data comparison using JSON serialization
   */
  private defaultCompare(prev: any, current: any): boolean {
    try {
      return JSON.stringify(prev) === JSON.stringify(current);
    } catch {
      // Fallback to reference equality if serialization fails
      return prev === current;
    }
  }
}

/**
 * React Hook for Adaptive Polling
 * 
 * Provides a React-friendly interface to the AdaptivePoller class.
 * Manages polling lifecycle tied to component mount/unmount.
 * 
 * Requirements: 5.1
 */

import { useEffect, useState, useRef, useCallback } from 'react';

export interface UseAdaptivePollingOptions extends AdaptivePollerOptions {
  enabled?: boolean; // Whether polling is enabled (default: true)
}

export interface UseAdaptivePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  isPaused: boolean;
  refetch: () => Promise<void>;
  pause: () => void;
  resume: () => void;
}

export function useAdaptivePolling<T>(
  fetchFn: () => Promise<T>,
  options: UseAdaptivePollingOptions
): UseAdaptivePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [isPaused, setIsPaused] = useState<boolean>(false);

  const pollerRef = useRef<AdaptivePoller<T> | null>(null);
  const fetchFnRef = useRef(fetchFn);

  // Keep fetchFn reference up to date
  useEffect(() => {
    fetchFnRef.current = fetchFn;
  }, [fetchFn]);

  // Wrapped fetch function that updates React state
  const wrappedFetchFn = useCallback(async (): Promise<T> => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchFnRef.current();
      setData(result);
      setLoading(false);
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      setLoading(false);
      throw error;
    }
  }, []);

  // Manual refetch function
  const refetch = useCallback(async (): Promise<void> => {
    await wrappedFetchFn();
  }, [wrappedFetchFn]);

  // Pause function
  const pause = useCallback(() => {
    if (pollerRef.current) {
      pollerRef.current.pause();
      setIsPaused(true);
    }
  }, []);

  // Resume function
  const resume = useCallback(() => {
    if (pollerRef.current) {
      pollerRef.current.resume();
      setIsPaused(false);
    }
  }, []);

  // Initialize and manage poller lifecycle
  useEffect(() => {
    const enabled = options.enabled ?? true;

    if (!enabled) {
      return;
    }

    // Create poller instance
    const poller = new AdaptivePoller<T>(wrappedFetchFn, options);
    pollerRef.current = poller;

    // Start polling
    poller.start();

    // Initial fetch
    wrappedFetchFn().catch(() => {
      // Error already handled in wrappedFetchFn
    });

    // Cleanup on unmount
    return () => {
      poller.stop();
      pollerRef.current = null;
    };
  }, [
    options.initialInterval,
    options.minInterval,
    options.maxInterval,
    options.enabled,
    wrappedFetchFn,
  ]);

  return {
    data,
    loading,
    error,
    isPaused,
    refetch,
    pause,
    resume,
  };
}
