"use client";
import { useEffect, useState } from "react";
import { api, type ApprovalQueueItem, formatINR, timeAgo } from "@/lib/api";
import { Check, X } from "lucide-react";
import { useWebSocket, getWebSocketUrl } from "@/lib/websocket-client";
import { useCachedFetch } from "@/lib/cache-manager";
import { useAdaptivePolling } from "@/lib/adaptive-poller";

export default function ApprovalQueue() {
  const [items, setItems] = useState<ApprovalQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState<Record<string, boolean>>({});
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  // WebSocket integration for real-time updates
  const { isConnected, lastMessage } = useWebSocket(getWebSocketUrl());

  // Cached fetch
  const {
    data: cachedData,
    loading: cachedLoading,
    refetch,
  } = useCachedFetch<ApprovalQueueItem[]>('/api/approvals/', {
    pollingInterval: 0,
  });

  // Adaptive polling (disabled when WebSocket connected)
  const {
    data: polledData,
    loading: polledLoading,
    refetch: polledRefetch,
  } = useAdaptivePolling<ApprovalQueueItem[]>(
    async () => api.fetchApprovals(),
    {
      initialInterval: 5_000,
      minInterval: 5_000,
      maxInterval: 60_000,
      enabled: !isConnected,
    }
  );

  // Update items from WebSocket messages
  useEffect(() => {
    if (lastMessage?.type === 'approval_pending') {
      const newApproval = lastMessage.data as ApprovalQueueItem;
      setItems(prev => [newApproval, ...prev]);
    }
  }, [lastMessage]);

  // Update items from cached fetch or polling
  useEffect(() => {
    const newData = isConnected ? cachedData : polledData;
    if (newData) {
      setItems(newData.filter((i) => i.status === "pending"));
    }
  }, [cachedData, polledData, isConnected]);

  // Update loading state
  useEffect(() => {
    setLoading(isConnected ? cachedLoading : polledLoading);
  }, [cachedLoading, polledLoading, isConnected]);

  async function handleApprove(id: string) {
    setProcessing((p) => ({ ...p, [id]: true }));
    try {
      await api.approveAction(id);
      // Refetch data after approval
      if (isConnected) {
        await refetch();
      } else {
        await polledRefetch();
      }
    } catch { /* noop */ } finally {
      setProcessing((p) => ({ ...p, [id]: false }));
    }
  }

  async function handleReject(id: string) {
    if (!rejectReason.trim()) return;
    setProcessing((p) => ({ ...p, [id]: true }));
    try {
      await api.rejectAction(id, rejectReason);
      setRejectingId(null);
      setRejectReason("");
      // Refetch data after rejection
      if (isConnected) {
        await refetch();
      } else {
        await polledRefetch();
      }
    } catch { /* noop */ } finally {
      setProcessing((p) => ({ ...p, [id]: false }));
    }
  }

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">🔐 Approval Queue</span>
        <span style={{
          background: items.length > 0 ? "var(--sev-critical-bg)" : "var(--bg-elevated)",
          color: items.length > 0 ? "var(--sev-critical)" : "var(--text-muted)",
          border: items.length > 0 ? "1px solid rgba(239,68,68,0.2)" : "1px solid var(--border)",
          borderRadius: 20, padding: "1px 10px", fontSize: 11, fontWeight: 600,
        }}>
          {items.length} pending
        </span>
      </div>
      <div className="panel-scroll">
        {items.length === 0 && !loading ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>✅</div>
            <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
              No pending approvals
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 11, marginTop: 4 }}>
              Actions below ₹50,000 are auto-executed
            </div>
          </div>
        ) : (
          <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
            {items.map((item, i) => (
              <div
                key={item.id || `approval-${i}`}
                style={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  padding: "14px 16px",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "var(--text-primary)" }}>
                      {item.action_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      Requested by {item.requested_by} · {timeAgo(item.requested_at)}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="inr" style={{ fontSize: 20, fontWeight: 800, color: "var(--sev-critical)" }}>
                      {formatINR(item.cost_impact_inr)}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>cost impact</div>
                  </div>
                </div>

                {/* Alert: exceeds auto-approve limit */}
                <div style={{
                  background: "rgba(239,68,68,0.06)",
                  border: "1px solid rgba(239,68,68,0.15)",
                  borderRadius: 6, padding: "6px 10px", marginBottom: 10,
                  fontSize: 11, color: "var(--sev-high)",
                }}>
                  ⚠️ Exceeds ₹50,000 auto-approve limit — manual review required
                </div>

                {rejectingId === item.id ? (
                  <div style={{ display: "flex", gap: 8 }}>
                    <input
                      className="input"
                      style={{ flex: 1 }}
                      placeholder="Rejection reason..."
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      autoFocus
                    />
                    <button
                      className="btn btn-danger"
                      onClick={() => handleReject(item.id)}
                      disabled={processing[item.id] || !rejectReason.trim()}
                    >
                      {processing[item.id] ? <span className="spinner" /> : <><X size={13} /> Confirm</>}
                    </button>
                    <button
                      className="btn btn-ghost"
                      onClick={() => { setRejectingId(null); setRejectReason(""); }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      className="btn btn-success"
                      style={{ flex: 1 }}
                      onClick={() => handleApprove(item.id)}
                      disabled={processing[item.id]}
                    >
                      {processing[item.id] ? <span className="spinner" /> : <><Check size={14} /> Approve</>}
                    </button>
                    <button
                      className="btn btn-danger"
                      style={{ flex: 1 }}
                      onClick={() => setRejectingId(item.id)}
                      disabled={processing[item.id]}
                    >
                      <X size={14} /> Reject
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
