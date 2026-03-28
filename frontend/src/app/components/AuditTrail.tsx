"use client";
import { useEffect, useState } from "react";
import { api, type AuditRecord, timeAgo, modelClass, modelLabel } from "@/lib/api";
import { ChevronDown, ChevronUp } from "lucide-react";

function ReasoningChain({ chain }: { chain: string[] }) {
  if (!chain?.length) return null;
  return (
    <div className="reasoning-steps">
      <div style={{ fontSize: 11, color: "var(--deepseek)", fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 5 }}>
        🤖 DeepSeek Reasoning Chain
      </div>
      {chain.map((step, i) => (
        <div key={i} className="reasoning-step">
          <div className="step-num">{i + 1}</div>
          <div>{step}</div>
        </div>
      ))}
    </div>
  );
}

function AuditRow({ record }: { record: AuditRecord }) {
  const [expanded, setExpanded] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");

  const chain: string[] = (() => {
    if (!record.reasoning_output) return [];
    const ro = record.reasoning_output as Record<string, unknown>;
    if (Array.isArray(ro.reasoning_chain)) return ro.reasoning_chain as string[];
    return [];
  })();

  async function handleOverride() {
    if (!overrideReason.trim()) return;
    setOverriding(true);
    try {
      await api.overrideAudit(record.audit_id, overrideReason);
      setOverrideReason("");
      setExpanded(false);
    } catch { /* noop */ } finally {
      setOverriding(false);
    }
  }

  return (
    <>
      <tr onClick={() => setExpanded((v) => !v)}>
        <td>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {record.audit_id.slice(-8)}
          </div>
        </td>
        <td style={{ fontSize: 11, color: "var(--text-secondary)" }}>
          {timeAgo(record.timestamp)}
        </td>
        <td style={{ fontSize: 12 }}>{record.agent?.replace("Agent", "")}</td>
        <td>
          {record.model_used ? (
            <span className={`model-pill ${modelClass(record.model_used)}`}>
              {modelLabel(record.model_used)}
            </span>
          ) : "—"}
        </td>
        <td>
          {record.reasoning_invoked ? (
            <span className="model-pill model-deepseek">🧠 deepseek</span>
          ) : (
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>—</span>
          )}
        </td>
        <td>
          <span className={`badge ${
            record.final_status === "success"    ? "badge-success" :
            record.final_status === "error"      ? "badge-failed"   :
            record.final_status === "overridden" ? "badge-pending" : ""
          }`}>
            {record.final_status}
          </span>
        </td>
        <td style={{ textAlign: "right" }}>
          {expanded ? <ChevronUp size={13} color="var(--text-muted)" /> : <ChevronDown size={13} color="var(--text-muted)" />}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: "0 16px 14px", background: "var(--bg-elevated)" }}>
            {chain.length > 0 && <ReasoningChain chain={chain} />}
            {record.final_status !== "overridden" && (
              <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                <input
                  className="input"
                  style={{ flex: 1 }}
                  placeholder="Override reason..."
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  className="btn btn-ghost"
                  style={{ fontSize: 12 }}
                  onClick={(e) => { e.stopPropagation(); handleOverride(); }}
                  disabled={overriding || !overrideReason.trim()}
                >
                  {overriding ? <span className="spinner" /> : "Override"}
                </button>
              </div>
            )}
            {record.override_reason && (
              <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
                Override: {record.override_reason}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function AuditTrail() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const data = await api.fetchAudit(50);
      setRecords(data);
    } catch { /* noop */ } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">📋 Audit Trail</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{records.length} records</span>
      </div>
      <div className="panel-scroll">
        {records.length === 0 && !loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No audit records yet. Run a scan to generate records.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>When</th>
                <th>Agent</th>
                <th>Model</th>
                <th>Reasoning</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <AuditRow key={r.audit_id} record={r} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
