/**
 * useDashboardData hook — optimized dashboard data fetching with aggregated endpoint.
 * 
 * This hook implements the dashboard initial load optimization by:
 * 1. First attempting to fetch from the aggregated /api/dashboard/summary endpoint
 * 2. Pre-populating the cache with aggregated data so individual component requests hit cache
 * 3. Falling back to individual endpoint requests if aggregated fails (404, 500, network error)
 * 
 * Requirements: 3.5, 9.6
 * Property 20: Aggregated Endpoint Fallback
 */

import { useState, useEffect, useCallback } from "react";
import { api, SavingsSummary, Anomaly, Action, ApprovalQueueItem, SystemStatus } from "./api";
import { cacheManager } from "./cache-manager";

// ── Types ───────────────────────────────────────────────────────────────────

interface DashboardSummary {
  savings: SavingsSummary;
  recent_anomalies: Anomaly[];
  recent_actions: Action[];
  pending_approvals_count: number;
  system_status: SystemStatus;
  timestamp: string;
}

interface DashboardSummaryResponse {
  data: DashboardSummary | null;
  errors: Record<string, string>;
  partial: boolean;
}

export interface DashboardData {
  savings: SavingsSummary | null;
  anomalies: Anomaly[];
  actions: Action[];
  approvals: ApprovalQueueItem[];
  systemStatus: SystemStatus | null;
  pendingApprovalsCount: number;
}

interface UseDashboardDataResult {
  data: DashboardData | null;
  loading: boolean;
  error: Error | null;
  usedFallback: boolean;
  refetch: () => Promise<void>;
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useDashboardData(): UseDashboardDataResult {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [usedFallback, setUsedFallback] = useState(false);

  const fetchDashboardData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUsedFallback(false);

    try {
      // Attempt to fetch from aggregated endpoint
      const response = await fetchAggregatedEndpoint();
      
      if (response) {
        // Successfully fetched from aggregated endpoint
        setData(response);
        setLoading(false);
        return;
      }
    } catch (err) {
      // Aggregated endpoint failed, fall back to individual endpoints
      console.warn("Aggregated endpoint failed, falling back to individual endpoints:", err);
      setUsedFallback(true);
      
      try {
        const fallbackData = await fetchIndividualEndpoints();
        setData(fallbackData);
        setLoading(false);
        return;
      } catch (fallbackErr) {
        // Both aggregated and fallback failed
        setError(fallbackErr instanceof Error ? fallbackErr : new Error(String(fallbackErr)));
        setLoading(false);
        return;
      }
    }
  }, []);

  useEffect(() => {
    fetchDashboardData();
  }, [fetchDashboardData]);

  return {
    data,
    loading,
    error,
    usedFallback,
    refetch: fetchDashboardData,
  };
}

// ── Helper Functions ────────────────────────────────────────────────────────

/**
 * Fetch data from the aggregated /api/dashboard/summary endpoint.
 * Pre-populates the cache with individual endpoint data so component requests hit cache.
 * Returns null if the endpoint is unavailable (404) or fails (500, network error).
 * 
 * Requirements: 3.5
 */
async function fetchAggregatedEndpoint(): Promise<DashboardData | null> {
  try {
    const res = await fetch("/api/dashboard/summary", { cache: "no-store" });
    
    // If endpoint doesn't exist (404) or server error (500), return null to trigger fallback
    if (res.status === 404 || res.status >= 500) {
      return null;
    }
    
    if (!res.ok) {
      throw new Error(`Aggregated endpoint failed with status ${res.status}`);
    }
    
    const response: DashboardSummaryResponse = await res.json();
    
    // If response has no data, return null to trigger fallback
    if (!response.data) {
      return null;
    }
    
    // Pre-populate cache with individual endpoint data
    // This ensures that when components make their requests, they hit the cache
    // instead of making new HTTP requests
    const baseUrl = typeof window !== 'undefined' ? window.location.origin : '';
    
    // Cache savings data
    if (response.data.savings) {
      cacheManager.setCacheEntry(
        `${baseUrl}/api/savings/summary`,
        response.data.savings,
        'dummy-etag-from-aggregated' // ETag will be updated on next real request
      );
    }
    
    // Cache anomalies data
    if (response.data.recent_anomalies) {
      cacheManager.setCacheEntry(
        `${baseUrl}/api/anomalies/?limit=20`,
        response.data.recent_anomalies,
        'dummy-etag-from-aggregated'
      );
    }
    
    // Cache actions data
    if (response.data.recent_actions) {
      cacheManager.setCacheEntry(
        `${baseUrl}/api/actions/?limit=20`,
        response.data.recent_actions,
        'dummy-etag-from-aggregated'
      );
    }
    
    // Cache system status data
    if (response.data.system_status) {
      cacheManager.setCacheEntry(
        `${baseUrl}/api/system/status`,
        response.data.system_status,
        'dummy-etag-from-aggregated'
      );
    }
    
    // Transform aggregated response to DashboardData format
    return {
      savings: response.data.savings,
      anomalies: response.data.recent_anomalies,
      actions: response.data.recent_actions,
      approvals: [], // Aggregated endpoint doesn't include full approval list, will be fetched separately if needed
      systemStatus: response.data.system_status,
      pendingApprovalsCount: response.data.pending_approvals_count,
    };
  } catch (err) {
    // Network error or parsing error, return null to trigger fallback
    console.error("Error fetching aggregated endpoint:", err);
    return null;
  }
}

/**
 * Fallback: fetch data from individual component endpoints.
 * This is used when the aggregated endpoint is unavailable.
 * 
 * Requirements: 9.6
 * Property 20: Aggregated Endpoint Fallback
 */
async function fetchIndividualEndpoints(): Promise<DashboardData> {
  // Fetch all endpoints in parallel
  const [savings, anomalies, actions, approvals, systemStatus] = await Promise.all([
    api.fetchSavings().catch((err) => {
      console.error("Failed to fetch savings:", err);
      return null;
    }),
    api.fetchAnomalies(10).catch((err) => {
      console.error("Failed to fetch anomalies:", err);
      return [];
    }),
    api.fetchActions(10).catch((err) => {
      console.error("Failed to fetch actions:", err);
      return [];
    }),
    api.fetchApprovals().catch((err) => {
      console.error("Failed to fetch approvals:", err);
      return [];
    }),
    api.fetchSystemStatus().catch((err) => {
      console.error("Failed to fetch system status:", err);
      return null;
    }),
  ]);

  return {
    savings,
    anomalies,
    actions,
    approvals,
    systemStatus,
    pendingApprovalsCount: approvals.length,
  };
}
