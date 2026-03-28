"use client";
import { useEffect, useState } from "react";
import { api, type Action, formatINR, timeAgo, actionTypeLabel, modelClass, modelLabel } from "@/lib/api";
import {
  CreditCard, Mail, Shield, Users, AlertTriangle, Tag, Server,
} from "lucide-react";

const ACTION_ICONS: Record<string, React.ReactNode> = {
  payment_hold:              <CreditCard size={14} color="var(--sev-critical)" />,
  payment_release:           <CreditCard size={14} color="var(--success)" />,
  email_sent:                <Mail size={14} color="var(--sev-low)" />,
  license_deactivated:       <Users size={14} color="var(--sev-high)" />,
  license_restored:          <Users size={14} color="var(--success)" />,
  sla_escalation:            <AlertTriangle size={14} color="var(--pending)" />,
  vendor_renegotiation_flag: <Tag size={14} color="var(--sev-medium)" />,
  resource_downsize:         <Server size={14} color="var(--accent)" />,
};

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    success:          "badge-success",
    pending:          "badge-pending",
    pending_approval: "badge-pending",
    failed:           "badge-failed",
    rolled_back:      "badge-failed",
    rejected:         "badge-failed",
    approved:         "badge-success",
  };
  return <span className={`badge ${map[status] ?? ""}`}>{status.replace(/_/g, " ")}</span>;
}

export default function ActionsPanel() {
  const [actions, setActions] = useState<Action[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const data = await api.fetchActions(20);
      setActions(data);
    } catch { /* noop */ } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, []);

  const counts = {
    success:  actions.filter((a) => a.status === "success").length,
    pending:  actions.filter((a) => a.status.includes("pending")).length,
    failed:   actions.filter((a) => ["failed","rejected","rolled_back"].includes(a.status)).length,
  };

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">⚡ Actions Executed</span>
        <div style={{ display: "flex", gap: 8, fontSize: 11 }}>
          <span style={{ color: "var(--success)" }}>✓ {counts.success}</span>
          <span style={{ color: "var(--pending)" }}>⏳ {counts.pending}</span>
          <span style={{ color: "var(--failed)" }}>✗ {counts.failed}</span>
        </div>
      </div>
      <div className="panel-scroll">
        {actions.length === 0 && !loading ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
            No actions taken yet.
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Status</th>
                <th>Saved</th>
                <th>Model</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((a, i) => (
                <tr key={a.id} className="anim-fade-in" style={{ animationDelay: `${i * 30}ms` }}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {ACTION_ICONS[a.action_type] ?? <Shield size={14} />}
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 13 }}>
                          {actionTypeLabel(a.action_type)}
                        </div>
                        {a.anomaly_type && (
                          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                            {a.anomaly_type.replace(/_/g, " ")}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td><StatusBadge status={a.status} /></td>
                  <td>
                    {Number(a.cost_saved) > 0 ? (
                      <span className="inr" style={{ color: "var(--success)", fontWeight: 600, fontSize: 13 }}>
                        {formatINR(a.cost_saved)}
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)" }}>—</span>
                    )}
                  </td>
                  <td>
                    {a.executed_by ? (
                      <span className={`model-pill ${modelClass(a.executed_by)}`}>
                        {modelLabel(a.executed_by)}
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: 11 }}>system</span>
                    )}
                  </td>
                  <td style={{ color: "var(--text-muted)", fontSize: 11 }}>
                    {timeAgo(a.executed_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
