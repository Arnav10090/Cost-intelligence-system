"use client";
import { useEffect, useState } from "react";
import { api, type Anomaly, formatINR, timeAgo, anomalyTypeLabel } from "@/lib/api";
import { ChevronDown, ChevronUp, RefreshCw } from "lucide-react";
import { useWebSocket, getWebSocketUrl } from "@/lib/websocket-client";
import { useCachedFetch } from "@/lib/cache-manager";
import { useAdaptivePolling } from "@/lib/adaptive-poller";

function SeverityBadge({ sev }: { sev: string | null | undefined }) {
  if (!sev) {
    return <span className="badge badge-muted">—</span>;
  }
  
  const cls: Record<string, string> = {
    CRITICAL: "badge-critical",
    HIGH:     "badge-high",
    MEDIUM:   "badge-medium",
    LOW:      "badge-low",
  };
  return <span className={`badge ${cls[sev?.toUpperCase()] ?? "badge-low"}`}>{sev}</span>;
}

function AnomalyRow({ anomaly, idx }: { anomaly: Anomaly; idx: number }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <tr
        onClick={() => setExpanded((v) => !v)}
        className="anim-fade-in"
        style={{ animationDelay: `${idx * 30}ms` }}
      >
        <td>
          <div style={{ fontWeight: 600, fontSize: 13, color: "var(--text-primary)" }}>
            {anomalyTypeLabel(anomaly.anomaly_type)}
          </div>
        </td>
        <td><SeverityBadge sev={anomaly.severity} /></td>
        <td>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div className="progress" style={{ width: 48 }}>
              <div
                className="progress-bar"
                style={{ width: `${anomaly.confidence != null && !isNaN(Number(anomaly.confidence)) ? Math.round(Number(anomaly.confidence) * 100) : 0}%` }}
              />
            </div>
            <span className="mono" style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              {anomaly.confidence != null && !isNaN(Number(anomaly.confidence)) ? `${Math.round(Number(anomaly.confidence) * 100)}%` : '—'}
            </span>
          </div>
        </td>
        <td className="inr" style={{ color: "var(--sev-high)", fontWeight: 600 }}>
          {formatINR(anomaly.cost_impact_inr)}
        </td>
        <td>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{timeAgo(anomaly.detected_at)}</span>
        </td>
        <td>
          <span className={`badge ${
            anomaly.status === "actioned" ? "badge-success" :
            anomaly.status === "dismissed" ? "" : "badge-pending"
          }`} style={anomaly.status === "dismissed" ? { color: "var(--text-muted)" } : {}}>
            {anomaly.status}
          </span>
        </td>
        <td style={{ textAlign: "right" }}>
          {expanded ? <ChevronUp size={14} color="var(--text-muted)" /> : <ChevronDown size={14} color="var(--text-muted)" />}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: "0 16px 12px" }}>
            <div style={{
              background: "var(--bg-elevated)", borderRadius: 8, padding: "12px 16px",
              fontSize: 12, color: "var(--text-secondary)", border: "1px solid var(--border)",
            }}>
              {anomaly.root_cause && (
                <div style={{ marginBottom: 6 }}>
                  <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>Root cause: </span>
                  {anomaly.root_cause}
                </div>
              )}
              {anomaly.model_used && (
                <div>
                  <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>Model: </span>
                  <span className={`model-pill ${
                    anomaly.model_used.includes("deepseek") ? "model-deepseek" :
                    anomaly.model_used.includes("qwen") ? "model-qwen" : "model-llama"
                  }`}>
                    {anomaly.model_used}
                  </span>
                </div>
              )}
              {anomaly.latest_action && (
                <div style={{ marginTop: 6 }}>
                  <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>Action taken: </span>
                  {anomaly.latest_action} ({anomaly.action_status})
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function AnomalyFeed() {
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);

  // WebSocket integration for real-time updates
  const { isConnected, lastMessage } = useWebSocket(getWebSocketUrl());

  // Cached fetch
  const {
    data: cachedData,
    loading: cachedLoading,
  } = useCachedFetch<Anomaly[]>('/api/anomalies/?limit=20', {
    pollingInterval: 0,
  });

  // Adaptive polling (disabled when WebSocket connected)
  const {
    data: polledData,
    loading: polledLoading,
  } = useAdaptivePolling<Anomaly[]>(
    async () => api.fetchAnomalies(20),
    {
      initialInterval: 10_000,
      minInterval: 5_000,
      maxInterval: 60_000,
      enabled: !isConnected,
    }
  );

  // Update anomalies from WebSocket messages
  useEffect(() => {
    if (lastMessage?.type === 'anomaly_created') {
      const newAnomaly = lastMessage.data as Anomaly;
      setAnomalies(prev => [newAnomaly, ...prev].slice(0, 20));
    }
  }, [lastMessage]);

  // Update anomalies from cached fetch or polling
  useEffect(() => {
    const newData = isConnected ? cachedData : polledData;
    if (newData) {
      setAnomalies(newData);
    }
  }, [cachedData, polledData, isConnected]);

  // Update loading state
  useEffect(() => {
    setLoading(isConnected ? cachedLoading : polledLoading);
  }, [cachedLoading, polledLoading, isConnected]);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">🔍 Anomaly Feed</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{anomalies.length} detections</span>
          {loading && <RefreshCw size={12} color="var(--text-muted)" className="spinner" />}
        </div>
      </div>
      <div className="panel-scroll">
        {anomalies.length === 0 && !loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No anomalies detected yet. The system is scanning...
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Severity</th>
                <th>Confidence</th>
                <th>Cost Impact</th>
                <th>Detected</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {anomalies.map((a, i) => (
                <AnomalyRow key={a.id || `anomaly-${i}`} anomaly={a} idx={i} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
