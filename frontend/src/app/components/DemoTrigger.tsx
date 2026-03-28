"use client";
import { useState, useEffect } from "react";
import { api, DemoScenario } from "@/lib/api";
import { Zap, RotateCcw, CheckCircle, XCircle, ChevronRight } from "lucide-react";

// ── Per-scenario pipeline steps ──────────────────────────────────────────────
const SCENARIO_STEPS: Record<string, { key: string; label: string }[]> = {
  duplicate_payment: [
    { key: "inject",  label: "Injecting duplicate payment (₹1,00,000 · PO-DEMO-001)" },
    { key: "scan",    label: "Scanning for anomalies..." },
    { key: "reason",  label: "DeepSeek-R1 reasoning..." },
    { key: "act",     label: "Holding payment + sending alert email..." },
    { key: "audit",   label: "Writing audit trail..." },
    { key: "done",    label: "Pipeline complete ✅" },
  ],
  sla_breach: [
    { key: "inject",  label: "Injecting SLA ticket (P1 · 4h SLA · 3.3h elapsed)" },
    { key: "scan",    label: "Computing breach probability..." },
    { key: "reason",  label: "DeepSeek-R1 risk assessment..." },
    { key: "act",     label: "Escalating ticket + sending alert..." },
    { key: "audit",   label: "Writing audit trail..." },
    { key: "done",    label: "Pipeline complete ✅" },
  ],
  unused_subscriptions: [
    { key: "inject",  label: "Injecting 5 ghost licenses (₹15,000/month)" },
    { key: "scan",    label: "Scanning for unused subscriptions..." },
    { key: "reason",  label: "Qwen 2.5 analysis..." },
    { key: "act",     label: "Bulk deactivating 5 licenses..." },
    { key: "audit",   label: "Writing audit trail..." },
    { key: "done",    label: "Pipeline complete ✅" },
  ],
  approval_queue: [
    { key: "inject",  label: "Injecting ₹75,000 duplicate (above ₹50k auto-approve)" },
    { key: "scan",    label: "Scanning for anomalies..." },
    { key: "reason",  label: "DeepSeek-R1 reasoning..." },
    { key: "act",     label: "Routing to approval queue (₹75k > ₹50k limit)..." },
    { key: "audit",   label: "Writing audit trail..." },
    { key: "done",    label: "Awaiting human approval ✅" },
  ],
};

const COMPLETION_MESSAGES: Record<string, string> = {
  duplicate_payment:    "✅ Duplicate detected, payment held, audit written. Check Anomaly Feed & Actions panel.",
  sla_breach:           "✅ SLA breach risk flagged (P≈0.85), ticket escalated. Check Anomaly Feed.",
  unused_subscriptions: "✅ 5 ghost licenses deactivated, ₹15,000/month saved. Check Actions panel.",
  approval_queue:       "✅ ₹75,000 duplicate routed to Approval Queue. Click Approve in the queue below!",
};

// Fallback scenarios if API is unreachable
const FALLBACK_SCENARIOS: DemoScenario[] = [
  { id: "duplicate_payment",    title: "Duplicate Payment",    description: "₹1,00,000 duplicate with same PO", amount_display: "₹1,00,000", icon: "💳", severity: "HIGH" },
  { id: "sla_breach",           title: "SLA Near-Breach",      description: "P1 ticket nearing 4h SLA deadline", amount_display: "₹25,000", icon: "⏱️", severity: "CRITICAL" },
  { id: "unused_subscriptions", title: "Unused Subscriptions", description: "5 licenses for ghost employees",    amount_display: "₹15,000/mo", icon: "🔑", severity: "MEDIUM" },
  { id: "approval_queue",       title: "Approval Queue",       description: "₹75,000 duplicate → needs approval", amount_display: "₹75,000", icon: "✅", severity: "HIGH" },
];

type StepStatus = "idle" | "active" | "done" | "error";

export default function DemoTrigger() {
  const [scenarios, setScenarios] = useState<DemoScenario[]>(FALLBACK_SCENARIOS);
  const [selected, setSelected] = useState("duplicate_payment");
  const [running, setRunning] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [stepStatus, setStepStatus] = useState<Record<string, StepStatus>>({});
  const [taskId, setTaskId] = useState<string | null>(null);
  const [finalError, setFinalError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);

  // Fetch scenario list from backend on mount
  useEffect(() => {
    api.fetchDemoScenarios()
      .then((res) => { if (res.scenarios?.length) setScenarios(res.scenarios); })
      .catch(() => { /* use fallback */ });
  }, []);

  function markStep(key: string, status: StepStatus) {
    setStepStatus((prev) => ({ ...prev, [key]: status }));
  }

  async function handleTrigger() {
    setRunning(true);
    setStepStatus({});
    setFinalError(null);
    setCompleted(false);

    const steps = SCENARIO_STEPS[selected] || SCENARIO_STEPS.duplicate_payment;

    try {
      // Step 1: Inject
      markStep("inject", "active");
      await sleep(400);

      const res = await api.triggerDemoScenario(selected);
      setTaskId(res.task_id ?? null);

      markStep("inject", "done");

      // Step 2: Scan
      markStep("scan", "active");
      await sleep(600);
      markStep("scan", "done");

      // Step 3: Reason
      markStep("reason", "active");
      await sleep(selected === "unused_subscriptions" ? 900 : 1500);
      markStep("reason", "done");

      // Step 4: Act
      markStep("act", "active");
      await sleep(800);
      markStep("act", "done");

      // Step 5: Audit
      markStep("audit", "active");
      await sleep(500);
      markStep("audit", "done");

      // Step 6: Done
      markStep("done", "done");
      setCompleted(true);
    } catch (err) {
      setFinalError(err instanceof Error ? err.message : "Pipeline failed — see backend logs");
      steps.forEach((s) => {
        if (stepStatus[s.key] === "active") markStep(s.key, "error");
      });
    } finally {
      setRunning(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    setStepStatus({});
    setFinalError(null);
    setCompleted(false);
    setTaskId(null);
    try {
      await api.resetDemo();
    } catch { /* noop */ } finally {
      setResetting(false);
    }
  }

  const steps = SCENARIO_STEPS[selected] || SCENARIO_STEPS.duplicate_payment;
  const sevColor: Record<string, string> = {
    CRITICAL: "var(--sev-critical)",
    HIGH: "var(--sev-high)",
    MEDIUM: "var(--sev-medium)",
    LOW: "var(--sev-low)",
  };

  return (
    <div className="card" style={{ height: "100%" }}>
      <div className="card-header">
        <span className="card-title">🎬 Demo Trigger</span>
        {taskId && (
          <span style={{ fontFamily: "monospace", fontSize: 10, color: "var(--text-muted)" }}>
            {taskId.slice(0, 16)}…
          </span>
        )}
      </div>
      <div style={{ padding: "16px 20px" }}>

        {/* ── Scenario Selector ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 14 }}>
          {scenarios.map((sc) => (
            <button
              key={sc.id}
              onClick={() => !running && setSelected(sc.id)}
              disabled={running}
              style={{
                display: "flex", flexDirection: "column", gap: 3,
                padding: "10px 12px", borderRadius: 10,
                border: selected === sc.id
                  ? "1.5px solid rgba(99,102,241,0.6)"
                  : "1px solid var(--border)",
                background: selected === sc.id
                  ? "var(--accent-glow)"
                  : "var(--bg-elevated)",
                cursor: running ? "not-allowed" : "pointer",
                textAlign: "left",
                transition: "all 0.2s",
                opacity: running && selected !== sc.id ? 0.4 : 1,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 16 }}>{sc.icon}</span>
                <span style={{
                  fontSize: 12, fontWeight: 700,
                  color: selected === sc.id ? "var(--text-primary)" : "var(--text-secondary)",
                }}>{sc.title}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{sc.amount_display}</span>
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4,
                  color: sevColor[sc.severity] || "var(--text-muted)",
                  background: `${sevColor[sc.severity] || "var(--text-muted)"}15`,
                }}>{sc.severity}</span>
              </div>
            </button>
          ))}
        </div>

        {/* ── Trigger Button ── */}
        <button
          className="demo-btn"
          onClick={handleTrigger}
          disabled={running || resetting}
          id="demo-trigger-btn"
        >
          {running ? (
            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
              <span className="spinner" />
              Running pipeline...
            </span>
          ) : (
            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <Zap size={18} />
              Simulate: {scenarios.find((s) => s.id === selected)?.title ?? "Cost Leak"}
              <ChevronRight size={14} style={{ opacity: 0.6 }} />
            </span>
          )}
        </button>

        {/* ── Progress Steps ── */}
        {Object.keys(stepStatus).length > 0 && (
          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 5 }}>
            {steps.map((step) => {
              const st = stepStatus[step.key] ?? "idle";
              return (
                <div
                  key={step.key}
                  style={{
                    display: "flex", alignItems: "center", gap: 10,
                    padding: "6px 10px", borderRadius: 7,
                    background: st === "active" ? "var(--accent-glow)"
                              : st === "done" ? "var(--success-bg)" : "transparent",
                    border: `1px solid ${
                      st === "active" ? "rgba(99,102,241,0.3)"
                    : st === "done" ? "rgba(34,197,94,0.15)" : "transparent"
                    }`,
                    transition: "all 0.3s",
                    opacity: st === "idle" ? 0.35 : 1,
                  }}
                >
                  {st === "done"   && <CheckCircle size={13} color="var(--success)" />}
                  {st === "active" && <span className="spinner" />}
                  {st === "error"  && <XCircle size={13} color="var(--failed)" />}
                  {st === "idle"   && <div style={{ width: 13, height: 13, borderRadius: "50%", border: "1px solid var(--border)" }} />}
                  <span style={{
                    fontSize: 11.5,
                    color: st === "done" ? "var(--success)" : st === "active" ? "var(--text-primary)" : "var(--text-muted)",
                    fontWeight: st === "active" ? 600 : 400,
                  }}>
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* ── Completion / Error ── */}
        {completed && (
          <div style={{
            marginTop: 12, padding: "10px 14px",
            background: "var(--success-bg)", border: "1px solid rgba(34,197,94,0.25)",
            borderRadius: 8, fontSize: 12, color: "var(--success)", fontWeight: 600,
          }}>
            {COMPLETION_MESSAGES[selected] || "Pipeline complete."}
          </div>
        )}
        {finalError && (
          <div style={{
            marginTop: 12, padding: "10px 14px",
            background: "var(--failed-bg)", border: "1px solid rgba(239,68,68,0.25)",
            borderRadius: 8, fontSize: 12, color: "var(--failed)",
          }}>
            ⚠️ {finalError}
          </div>
        )}

        {/* ── Reset ── */}
        <button
          className="btn btn-ghost"
          style={{ width: "100%", marginTop: 10, fontSize: 12 }}
          onClick={handleReset}
          disabled={running || resetting}
          id="demo-reset-btn"
        >
          {resetting ? <span className="spinner" /> : <><RotateCcw size={13} /> Reset Demo Data</>}
        </button>

        {/* ── Hint Card ── */}
        <div style={{
          marginTop: 12, padding: "10px", borderRadius: 8,
          background: "var(--bg-elevated)", border: "1px solid var(--border)",
          fontSize: 11, color: "var(--text-muted)", lineHeight: 1.6,
        }}>
          <strong style={{ color: "var(--text-secondary)" }}>
            {scenarios.find((s) => s.id === selected)?.icon}{" "}
            {scenarios.find((s) => s.id === selected)?.title}:
          </strong>
          <br />
          {scenarios.find((s) => s.id === selected)?.description}
        </div>
      </div>
    </div>
  );
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
