"use client";
import { useEffect, useRef, useState } from "react";
import { api, formatINR, type SavingsSummary } from "@/lib/api";
import { TrendingUp, DollarSign, Shield, Clock, Target } from "lucide-react";
import { useWebSocket, getWebSocketUrl } from "@/lib/websocket-client";
import { useCachedFetch } from "@/lib/cache-manager";
import { useAdaptivePolling } from "@/lib/adaptive-poller";

function AnimatedNumber({ value }: { value: number }) {
  const [display, setDisplay] = useState(value);
  const [flash, setFlash] = useState(false);
  const prevRef = useRef(value);

  useEffect(() => {
    if (prevRef.current === value) return;
    prevRef.current = value;
    setFlash(true);
    const step = (value - display) / 20;
    let cur = display;
    const timer = setInterval(() => {
      cur += step;
      if ((step > 0 && cur >= value) || (step < 0 && cur <= value)) {
        cur = value;
        clearInterval(timer);
      }
      setDisplay(Math.round(cur));
    }, 30);
    setTimeout(() => setFlash(false), 700);
    return () => clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <span className={flash ? "anim-flash" : ""} style={{ transition: "color 0.3s" }}>
      {formatINR(display)}
    </span>
  );
}

const CATEGORIES = [
  {
    key: "duplicate_payments_blocked" as keyof SavingsSummary,
    label: "Duplicate Payments",
    icon: Shield,
    color: "var(--sev-critical)",
  },
  {
    key: "unused_subscriptions_cancelled" as keyof SavingsSummary,
    label: "Unused Subscriptions",
    icon: Target,
    color: "var(--accent)",
  },
  {
    key: "sla_penalties_avoided" as keyof SavingsSummary,
    label: "SLA Penalties Avoided",
    icon: Clock,
    color: "var(--sev-high)",
  },
  {
    key: "reconciliation_errors_fixed" as keyof SavingsSummary,
    label: "Reconciliation Errors",
    icon: DollarSign,
    color: "var(--sev-medium)",
  },
];

export default function SavingsCounter() {
  const [data, setData] = useState<SavingsSummary | null>(null);
  const [error, setError] = useState(false);

  // WebSocket integration for real-time updates
  const { isConnected, lastMessage } = useWebSocket(getWebSocketUrl());

  // Cached fetch with adaptive polling fallback
  const {
    data: cachedData,
    loading,
    error: fetchError,
  } = useCachedFetch<SavingsSummary>('/api/savings/summary', {
    pollingInterval: 0, // Polling handled by adaptive poller
  });

  // Adaptive polling (disabled when WebSocket connected)
  const {
    data: polledData,
    isPaused,
  } = useAdaptivePolling<SavingsSummary>(
    async () => api.fetchSavings(),
    {
      initialInterval: 10_000,
      minInterval: 5_000,
      maxInterval: 60_000,
      enabled: !isConnected, // Disable when WebSocket connected
    }
  );

  // Update data from WebSocket messages
  useEffect(() => {
    if (lastMessage?.type === 'savings_updated') {
      setData(lastMessage.data as SavingsSummary);
      setError(false);
    }
  }, [lastMessage]);

  // Update data from cached fetch or polling
  useEffect(() => {
    const newData = isConnected ? cachedData : polledData;
    if (newData) {
      setData(newData);
      setError(false);
    }
  }, [cachedData, polledData, isConnected]);

  // Update error state
  useEffect(() => {
    if (fetchError) {
      setError(true);
    }
  }, [fetchError]);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">💰 Total Savings This Month</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
          <TrendingUp size={11} color="var(--success)" />
          Live · updates every 10s
        </span>
      </div>

      <div style={{ padding: "24px 24px 20px" }}>
        {/* Big counter */}
        <div style={{ marginBottom: 24, textAlign: "center" }}>
          {error ? (
            <div style={{ color: "var(--text-muted)", fontSize: 18 }}>Backend offline</div>
          ) : (
            <>
              <div className="counter-total">
                <AnimatedNumber value={data ? Number(data.total_savings_this_month) : 0} />
              </div>
              <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 8 }}>
                Annual projection:{" "}
                <span style={{ color: "var(--success)", fontWeight: 700, fontFamily: "monospace" }}>
                  {formatINR(data ? Number(data.annual_projection) : 0)}
                </span>
                /year
              </div>
            </>
          )}
        </div>

        {/* 4-category grid */}
        <div className="stat-grid">
          {CATEGORIES.map(({ key, label, icon: Icon, color }) => (
            <div key={key} className="stat-item">
              <div className="stat-label" style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <Icon size={11} color={color} />
                {label}
              </div>
              <div className="stat-value" style={{ color }}>
                {data ? formatINR(Number(data[key])) : "—"}
              </div>
            </div>
          ))}
        </div>

        {/* Footer bar */}
        {data && (
          <div style={{
            marginTop: 16,
            padding: "10px 14px",
            background: "var(--bg-elevated)",
            borderRadius: 8,
            display: "flex",
            justifyContent: "space-between",
            fontSize: 12,
            color: "var(--text-secondary)",
          }}>
            <span>
              ✅ <strong style={{ color: "var(--text-primary)" }}>{data.actions_taken_count}</strong> actions executed
            </span>
            <span>
              🔍 <strong style={{ color: "var(--text-primary)" }}>{data.anomalies_detected_count}</strong> anomalies detected
            </span>
            <span>
              ⏳ <strong style={{ color: "var(--pending)" }}>{data.pending_approvals_count}</strong> pending approval{data.pending_approvals_count !== 1 ? "s" : ""}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
