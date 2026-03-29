/**
 * API client — all fetch functions for the Cost Intelligence dashboard.
 * Uses Next.js built-in fetch via /api/* (proxied to FastAPI at :8000).
 */

// ── Types ───────────────────────────────────────────────────────────────────

export interface SavingsSummary {
  duplicate_payments_blocked: number;
  unused_subscriptions_cancelled: number;
  sla_penalties_avoided: number;
  reconciliation_errors_fixed: number;
  total_savings_this_month: number;
  annual_projection: number;
  actions_taken_count: number;
  anomalies_detected_count: number;
  pending_approvals_count: number;
}

export interface Anomaly {
  id: string;
  anomaly_type: string;
  severity: string;
  confidence: number;
  cost_impact_inr: number;
  status: string;
  detected_at: string;
  root_cause?: string;
  model_used?: string;
  entity_id?: string;
  latest_action?: string;
  action_status?: string;
}

export interface Action {
  id: string;
  anomaly_id?: string;
  action_type: string;
  status: string;
  cost_saved: number;
  executed_at: string;
  executed_by?: string;
  anomaly_type?: string;
  severity?: string;
  confidence?: number;
  approval_required?: boolean;
  rollback_payload?: Record<string, unknown>;
  model_used?: string;
  anomaly_model?: string;  // Model used from joined anomaly_logs
}

export interface AuditRecord {
  audit_id: string;
  timestamp: string;
  agent: string;
  model_used?: string;
  reasoning_invoked?: boolean;
  reasoning_model?: string;
  reasoning_output?: Record<string, unknown>;
  action_taken?: Record<string, unknown>;
  cost_impact_inr?: number;
  approval_status?: string;
  final_status: string;
  override_reason?: string;
}

export interface ApprovalQueueItem {
  id: string;
  action_id: string;
  anomaly_id?: string;
  action_type: string;
  cost_impact_inr: number;
  requested_by: string;
  requested_at: string;
  status: string;
  review_note?: string;
  expires_at?: string;
}

export interface ModelInfo {
  name: string;
  role: string;
  loaded: boolean;
  calls_this_hour?: number;
  budget_remaining?: number;
}

export interface SystemStatus {
  status: string;
  env: string;
  models: ModelInfo[];
  thresholds: {
    auto_approve_limit_inr: number;
    sla_escalation_threshold: number;
    duplicate_window_days: number;
    unused_license_days: number;
  };
  pending_approvals: number;
}

export interface DemoScenario {
  id: string;
  title: string;
  description: string;
  amount_display: string;
  icon: string;
  severity: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json();
}

// ── API functions ────────────────────────────────────────────────────────────

export const api = {
  fetchSavings: () =>
    get<SavingsSummary>("/api/savings/summary"),

  fetchAnomalies: (limit = 20) =>
    get<Anomaly[]>(`/api/anomalies/?limit=${limit}`),

  fetchActions: (limit = 20) =>
    get<Action[]>(`/api/actions/?limit=${limit}`),

  fetchAudit: (limit = 50) =>
    get<AuditRecord[]>(`/api/audit/?limit=${limit}`),

  fetchApprovals: () =>
    get<ApprovalQueueItem[]>("/api/approvals/"),

  fetchSystemStatus: () =>
    get<SystemStatus>("/api/system/status"),

  approveAction: (id: string, approved_by = "dashboard-user") =>
    post(`/api/approvals/${id}/approve`, { approved_by }),

  rejectAction: (id: string, reason: string, rejected_by = "dashboard-user") =>
    post(`/api/approvals/${id}/reject`, { rejected_by, reason }),

  triggerDemo: () =>
    post<{ task_id: string; message: string; scenario: string }>("/api/demo/trigger"),

  triggerDemoScenario: (scenario: string) =>
    post<{ task_id: string; message: string; scenario: string }>(
      `/api/demo/trigger?scenario=${encodeURIComponent(scenario)}`
    ),

  fetchDemoScenarios: () =>
    get<{ scenarios: DemoScenario[] }>("/api/demo/scenarios"),

  resetDemo: () =>
    post("/api/demo/reset"),

  getDemoStatus: (taskId: string) =>
    get<{ task_id: string; status: string; result?: unknown }>(`/api/demo/status/${taskId}`),

  overrideAudit: (auditId: string, reason: string, overridden_by = "dashboard-user") =>
    post(`/api/audit/${auditId}/override`, { override_reason: reason, overridden_by }),
};

// ── Utility: Indian number format ────────────────────────────────────────────

export function formatINR(amount: number | string | null | undefined): string {
  if (amount == null) return "₹0";
  const n = typeof amount === "string" ? parseFloat(amount) : Number(amount);
  if (isNaN(n) || !isFinite(n)) return "₹0";
  // Indian number system: last 3 digits, then groups of 2
  const parts = Math.abs(Math.round(n)).toString().split(".");
  const main = parts[0];
  let result = main;
  if (main.length > 3) {
    const last3 = main.slice(-3);
    const rest = main.slice(0, -3);
    result = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3;
  }
  return `₹${result}`;
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return "—";
    const secs = Math.floor((Date.now() - d.getTime()) / 1000);
    if (secs < 0) return "just now";
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
  } catch {
    return "—";
  }
}

export function severityColor(sev: string): string {
  switch (sev?.toUpperCase()) {
    case "CRITICAL": return "var(--sev-critical)";
    case "HIGH":     return "var(--sev-high)";
    case "MEDIUM":   return "var(--sev-medium)";
    case "LOW":      return "var(--sev-low)";
    default:         return "var(--text-secondary)";
  }
}

export function modelClass(model?: string | null): string {
  if (!model) return "model-unknown";
  if (model.includes("deepseek")) return "model-deepseek";
  if (model.includes("qwen"))     return "model-qwen";
  if (model.includes("llama"))    return "model-llama";
  return "model-unknown";
}

export function modelLabel(model?: string | null): string {
  if (!model) return "Unknown";
  if (model.includes("deepseek")) return "DeepSeek";
  if (model.includes("qwen"))     return "Qwen";
  if (model.includes("llama"))    return "Llama";
  return model;
}

export function anomalyTypeLabel(type: string | null | undefined): string {
  if (!type) return "Unknown";
  const map: Record<string, string> = {
    duplicate_payment:   "Duplicate Payment",
    unused_subscription: "Unused License",
    sla_risk:            "SLA Risk",
    reconciliation_gap:  "Reconciliation Gap",
    pricing_anomaly:     "Pricing Anomaly",
    infra_waste:         "Infra Waste",
  };
  return map[type] || type;
}

export function actionTypeLabel(type: string): string {
  const map: Record<string, string> = {
    payment_hold:              "Payment Hold",
    payment_release:           "Payment Release",
    email_sent:                "Email Sent",
    license_deactivated:       "License Deactivated",
    license_restored:          "License Restored",
    sla_escalation:            "SLA Escalated",
    vendor_renegotiation_flag: "Vendor Flag",
    resource_downsize:         "Resource Downsize",
  };
  return map[type] || type;
}
