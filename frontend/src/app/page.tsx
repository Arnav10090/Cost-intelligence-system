"use client";
import { useEffect } from "react";
import ModelStatus from "./components/ModelStatus";
import SavingsCounter from "./components/SavingsCounter";
import DemoTrigger from "./components/DemoTrigger";
import AnomalyFeed from "./components/AnomalyFeed";
import ActionsPanel from "./components/ActionsPanel";
import ApprovalQueue from "./components/ApprovalQueue";
import AuditTrail from "./components/AuditTrail";
import ConnectionStatus from "./components/ConnectionStatus";
import { useDashboardData } from "@/lib/useDashboardData";

export default function Dashboard() {
  // Use aggregated endpoint for initial load with fallback to individual endpoints
  const { data: dashboardData, loading, error, usedFallback } = useDashboardData();

  // Log fallback usage for monitoring
  useEffect(() => {
    if (usedFallback) {
      console.warn("Dashboard using fallback mode: aggregated endpoint unavailable");
    }
  }, [usedFallback]);

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      {/* ── Sticky nav / model status bar ── */}
      <ModelStatus />

      {/* ── Hero headline ── */}
      <div style={{
        padding: "28px 24px 0",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        paddingBottom: 20,
      }}>
        <div>
          <h1 style={{
            fontSize: 26, fontWeight: 800, color: "var(--text-primary)",
            letterSpacing: "-0.5px", marginBottom: 4,
          }}>
            Self‑Healing Cost Intelligence
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Autonomous anomaly detection · Real-time action execution · Full audit trail
          </p>
        </div>
        <div style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-end",
          gap: 8,
        }}>
          {/* Connection Status Indicator */}
          <ConnectionStatus />
          
          <div style={{
            fontSize: 12, color: "var(--text-muted)", textAlign: "right",
            display: "flex", flexDirection: "column", gap: 2,
          }}>
            <span style={{ color: "var(--text-secondary)", fontWeight: 600 }}>ET Gen AI Hackathon 2026</span>
            <span>Problem Statement #3</span>
          </div>
        </div>
      </div>

      {/* ── Main grid ── */}
      <div style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Row 1: Savings Counter (takes ~70%) + Demo Trigger (takes ~30%) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20 }}>
          <SavingsCounter />
          <DemoTrigger />
        </div>

        {/* Row 2: Anomaly Feed + Actions Panel (50/50) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
          <AnomalyFeed />
          <ActionsPanel />
        </div>

        {/* Row 3: Approval Queue (38%) + Audit Trail (62%) */}
        <div style={{ display: "grid", gridTemplateColumns: "38fr 62fr", gap: 20 }}>
          <ApprovalQueue />
          <AuditTrail />
        </div>

        {/* Footer */}
        <div style={{
          textAlign: "center", padding: "16px 0 8px",
          fontSize: 11, color: "var(--text-muted)",
          borderTop: "1px solid var(--border)",
        }}>
          <span>
            Stack: FastAPI · PostgreSQL · Redis · Ollama (Qwen 2.5 · DeepSeek-R1 · Llama 3.2) · Next.js 16
          </span>
          <span style={{ margin: "0 12px", color: "var(--border-bright)" }}>|</span>
          <span>All inference local · No data leaves the enterprise</span>
        </div>
      </div>
    </div>
  );
}
