"use client";
import { useEffect, useState } from "react";
import { api, type SystemStatus, modelLabel } from "@/lib/api";
import { Cpu, Clock, AlertTriangle, Activity } from "lucide-react";
import { useWebSocket, getWebSocketUrl } from "@/lib/websocket-client";
import { useCachedFetch } from "@/lib/cache-manager";

export default function ModelStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState(false);

  // WebSocket integration for real-time updates
  const { isConnected, lastMessage } = useWebSocket(getWebSocketUrl());

  // Cached fetch with fixed 30-second polling (not adaptive)
  const {
    data: cachedData,
    error: fetchError,
  } = useCachedFetch<SystemStatus>('/api/system/status', {
    pollingInterval: 30_000, // Fixed 30-second interval
  });

  // Update status from WebSocket messages
  useEffect(() => {
    if (lastMessage?.type === 'system_status_changed') {
      setStatus(lastMessage.data as SystemStatus);
      setLastUpdated(new Date());
      setError(false);
    }
  }, [lastMessage]);

  // Update status from cached fetch
  useEffect(() => {
    if (cachedData) {
      setStatus(cachedData);
      setLastUpdated(new Date());
      setError(false);
    }
  }, [cachedData]);

  // Update error state
  useEffect(() => {
    if (fetchError) {
      setError(true);
    }
  }, [fetchError]);

  const deepseek = status?.models.find((m) => m.name.includes("deepseek"));
  const qwen     = status?.models.find((m) => m.name.includes("qwen"));
  const llama    = status?.models.find((m) => m.name.includes("llama"));

  return (
    <nav className="navbar">
      {/* Left — branding */}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Activity size={18} color="var(--accent)" />
          <span style={{ fontWeight: 700, fontSize: 15, color: "var(--text-primary)" }}>
            Cost Intelligence
          </span>
          <span style={{
            fontSize: 10, fontWeight: 600, padding: "2px 7px",
            background: "var(--accent-glow)", color: "var(--accent)",
            borderRadius: 4, border: "1px solid rgba(99,102,241,0.3)",
          }}>
            ET GenAI 2026
          </span>
        </div>
      </div>

      {/* Center — model status */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {[
          { data: qwen,     cls: "model-qwen",     label: "Qwen" },
          { data: deepseek, cls: "model-deepseek",  label: "DeepSeek" },
          { data: llama,    cls: "model-llama",     label: "Llama" },
        ].map(({ data, cls, label }) => (
          <div key={label} className={`model-pill ${cls}`}>
            <span className="dot" style={{
              width: 6, height: 6, borderRadius: "50%",
              background: data?.loaded ? "var(--success)" : "var(--text-muted)",
              display: "inline-block",
            }} />
            {label}
            {data?.loaded && <span style={{ opacity: 0.7 }}>●</span>}
          </div>
        ))}
        {deepseek && (
          <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 4 }}>
            <Cpu size={11} />
            <span>
              DeepSeek: <span style={{ color: deepseek.calls_this_hour === 0 ? "var(--success)" : "var(--pending)" }}>
                {deepseek.calls_this_hour ?? 0}/10
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Right — pending approvals + time */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        {(status?.pending_approvals ?? 0) > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <AlertTriangle size={14} color="var(--pending)" />
            <span style={{ fontSize: 12, color: "var(--pending)", fontWeight: 600 }}>
              {status?.pending_approvals} pending approval{status!.pending_approvals !== 1 ? "s" : ""}
            </span>
          </div>
        )}
        {error && (
          <span style={{ fontSize: 11, color: "var(--failed)" }}>● Backend offline</span>
        )}
        {!error && lastUpdated && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--text-muted)", fontSize: 11 }}>
            <Clock size={11} />
            <span>{lastUpdated.toLocaleTimeString()}</span>
          </div>
        )}
      </div>
    </nav>
  );
}
