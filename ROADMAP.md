# Self-Healing Enterprise Cost Intelligence System
## Complete Build Roadmap — ET Gen AI Hackathon 2026

> **Purpose of this document:** This is a complete handoff file. If you are continuing this project in a new chat session, paste this entire document as your first message followed by: *"Continue building the Cost Intelligence System from Phase 2. All Phase 1 files are already on disk. Follow the roadmap exactly."*

---

## Problem Statement (Blueprint §1)

Build an AI system that goes beyond dashboards. It must continuously monitor enterprise operations data, identify cost leakage or inefficiency patterns, and initiate corrective actions with **quantifiable financial impact**.

**Evaluation Focus:** Quantifiable cost impact (show the math), ability to **take action** not just generate reports, data integration depth, enterprise approval workflows.

**Stack:** Ollama (local LLMs) · FastAPI · PostgreSQL · Redis · Next.js 14 · APScheduler

**Hardware target:** 16GB RAM · RTX 3050 4GB (CPU-primary inference, GPU not used for LLMs)

---

## Four Detection Targets

| Anomaly | Detection Logic | Confidence | Auto-action threshold |
|---|---|---|---|
| Duplicate payment | Same vendor + PO + amount ±2% within 30 days | 0.97 (same PO) / 0.82 (similar invoice) | >0.85 |
| Unused subscription | Terminated employee OR no login >60 days | 0.99 (terminated) / 0.75 (inactive) | >0.85 |
| SLA breach risk | `sigmoid(10 × (elapsed/sla - 0.75))` × modifiers | P(breach) ≥ 0.70 | Always escalate |
| Reconciliation gap | ERP vs bank delta >₹500 OR unmatched >48h | Rule-based | Always flag |

---

## Model Routing Rules (Blueprint §3 — CRITICAL)

```
LOW severity / error state / trivial  →  llama3.2:3b   (fallback, always loaded, ~2.5GB)
HIGH or CRITICAL severity             →  deepseek-r1:7b (reasoning, max 10 calls/hour)
Everything else                       →  qwen2.5:7b    (default, ~5.5GB)

NEVER load two 7B models simultaneously — swap via Ollama API (unload → load)
Peak RAM during swap: ~13.5GB (safe on 16GB)
```

**DeepSeek is invoked for ALL HIGH/CRITICAL** — not gated by confidence anymore (blueprint §3 UPDATE). Every high-impact financial decision needs an explainable reasoning chain in the audit log.

**Auto-approve limit: ₹50,000** — actions above this require human approval before execution.

---

## Current Project Structure (as of Phase 1 completion)

```
cost-intelligence/
├── docker-compose.yml          ✅ DONE — postgres, redis, mailhog; ollama runs natively
├── .env.example                ✅ DONE — copy to .env, OLLAMA_HOST=http://host.docker.internal:11434
├── ROADMAP.md                  ✅ THIS FILE
│
├── scripts/
│   ├── pull_models.sh          ✅ DONE — pulls all 3 Ollama models
│   ├── reset_demo.sh           ✅ DONE — truncates + re-seeds in ~3 seconds
│   └── check_health.sh         ✅ DONE — checks all services + DB row counts
│
├── backend/
│   ├── Dockerfile              ✅ DONE — python:3.12-slim-bookworm, single-stage
│   ├── requirements.txt        ✅ DONE — all deps pinned
│   ├── main.py                 ✅ DONE — lifespan, CORS, router registration, /api/system/status
│   │
│   ├── core/                   ✅ DONE
│   │   ├── __init__.py
│   │   ├── config.py           ✅ — Settings (pydantic-settings), ROUTING_CONFIG dict
│   │   ├── constants.py        ✅ — Severity, AnomalyType, ActionType, ActionState,
│   │   │                              ModelName, AgentName, TaskType, Confidence,
│   │   │                              RedisQueue enums
│   │   └── utils.py            ✅ — generate_audit_id(), sigmoid(), sla_breach_probability(),
│   │                                  levenshtein(), format_inr(), safe_jsonable(), utcnow()
│   │
│   ├── db/
│   │   ├── database.py         ✅ DONE — asyncpg pool, init_db(), get_db() dependency,
│   │   │                                  execute_schema(), get_connection()
│   │   ├── schema.sql          ✅ DONE — vendors, transactions, licenses, sla_metrics,
│   │   │                                  anomaly_logs, actions_taken, approval_queue,
│   │   │                                  audit_trail + all indexes
│   │   └── seed_data.py        ✅ DONE — 450 normal txns + 3 duplicate pairs,
│   │                                      200 licenses (29 terminated, 40 inactive),
│   │                                      50 SLA tickets (5 near-breach, no assignee)
│   │
│   ├── models/
│   │   └── schemas.py          ✅ DONE — Pydantic v2 models for all entities +
│   │                                      ApprovalQueueItem, ApproveRequest,
│   │                                      RejectRequest, OverrideRequest, SystemStatus
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   └── interfaces.py       ✅ DONE — AgentResult, DetectionResult, DecisionResult,
│   │                                      ActionResult, PipelineResult (all with to_audit_dict())
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── llm_router.py       ✅ DONE — select_model(), infer(), model swap, deepseek
│   │   │                                  call counter, timeout+fallback, prewarm_models(),
│   │   │                                  _extract_json() with <think> tag stripping
│   │   ├── approval_service.py ✅ DONE — requires_approval() gate, enqueue_for_approval(),
│   │   │                                  approve_action(), reject_action(), override_action(),
│   │   │                                  rollback dispatch, override audit write
│   │   │
│   │   └── action_handlers/    ✅ DONE
│   │       ├── __init__.py
│   │       ├── payment_handler.py     ✅ — hold_payment(), release_payment(),
│   │       │                               auto_release_stale_holds()
│   │       ├── license_handler.py     ✅ — deactivate_license(), restore_license(),
│   │       │                               bulk_deactivate_licenses(), get_unused_licenses()
│   │       ├── sla_handler.py         ✅ — escalate_ticket(), reroute_ticket(),
│   │       │                               close_ticket(), get_at_risk_tickets(),
│   │       │                               update_breach_probability()
│   │       └── notification_handler.py ✅ — send_alert_email(), email templates for
│   │                                         all 4 anomaly types, SMTP via MailHog
│   │
│   └── routers/
│       ├── __init__.py
│       ├── transactions.py     ✅ DONE — GET list, GET by id, POST create, PATCH hold, PATCH release
│       └── approvals.py        ✅ DONE — GET queue, GET stats, POST approve, POST reject, POST override
│
└── tests/
    ├── __init__.py
    ├── conftest.py             ✅ DONE — db_pool (session), db (per-test rollback), client,
    │                                      mock_ollama, mock_deepseek, seed_db fixtures
    ├── test_detection.py       ✅ DONE — levenshtein, fingerprint, SLA formula (all branches),
    │                                      confidence tiers, DB-backed detection queries
    ├── test_llm_router.py      ✅ DONE — routing tree, budget exhaustion, severity ordering,
    │                                      _extract_json, timeout→fallback integration
    ├── test_approval_flow.py   ✅ DONE — gate, approve/reject/override lifecycle,
    │                                      wrong-state transitions, ActionState enum
    └── test_cost_calculator.py ✅ DONE — all 4 blueprint §9 formulas, format_inr(),
                                           DB-backed savings sum, pending exclusion
```

---

## Running State (what is UP right now)

```powershell
# These 3 containers are running:
docker compose ps
# ci_postgres  healthy  → port 5432
# ci_redis     healthy  → port 6379
# ci_mailhog   running  → port 1025 (SMTP), 8025 (web UI)
# ci_backend   running  → port 8000  ← uvicorn with --reload (live file sync)

# Ollama running natively on Windows at http://localhost:11434
# Backend reaches it via http://host.docker.internal:11434

# Verify:
curl http://localhost:8000/health
curl http://localhost:8000/docs        # Swagger UI
```

**Important:** `./backend` is volume-mounted into the container. Edit files locally → uvicorn reloads automatically. Only run `docker compose build backend` when `requirements.txt` changes.

---

## Environment Setup

```
# .env (copy from .env.example, already configured):
POSTGRES_HOST=postgres          # Docker service name
REDIS_HOST=redis                # Docker service name
OLLAMA_HOST=http://host.docker.internal:11434   # Native Ollama on Windows host
SMTP_HOST=mailhog               # Docker service name
AUTO_APPROVE_LIMIT=50000        # ₹50,000 threshold for human approval
MODEL_DEFAULT=qwen2.5:7b
MODEL_REASONING=deepseek-r1:7b
MODEL_FALLBACK=llama3.2:3b
```

---

## ═══════════════════════════════════════════════════
## PHASE 2 — Core Agents  ← START HERE
## ═══════════════════════════════════════════════════

**Goal:** Build all 6 agents, Redis pub/sub, APScheduler, and the cost calculator. By end of Phase 2 the full pipeline runs end-to-end: data ingestion → anomaly detection → deepseek reasoning → action execution → audit logging.

### Files to create in Phase 2

#### `backend/services/redis_client.py`
- `init_redis()` / `close_redis()` — connect to Redis on startup/shutdown
- `publish_task(task: AgentTask)` — push to `ci:tasks` queue (LPUSH)
- `consume_tasks()` — async generator, BRPOP from `ci:tasks` with timeout
- `publish_result(result: dict)` — push to `ci:results`
- `get_redis()` — FastAPI dependency
- Use `redis.asyncio` (already in requirements.txt as `redis[hiredis]`)
- TTL: 30 minutes on all task keys (blueprint §12)

#### `backend/services/cost_calculator.py`
- `get_savings_summary(db) -> SavingsSummary` — queries actions_taken for sum by type
- `duplicate_savings(db) -> Decimal` — SUM(cost_saved) WHERE action_type='payment_hold' AND status='success'
- `subscription_savings(db) -> Decimal` — SUM(cost_saved) WHERE action_type='license_deactivated'
- `sla_savings(db) -> Decimal` — SUM(cost_saved) WHERE action_type='sla_escalation'
- `reconciliation_savings(db) -> Decimal`
- `annual_projection(monthly: Decimal) -> Decimal` — monthly × 12
- All formulas must match blueprint §9 exactly (judges check the math)

#### `backend/services/scheduler.py`
- Uses `APScheduler` with `AsyncIOScheduler`
- `start_scheduler()` / `stop_scheduler()`
- Jobs:
  - Every 15 min: `scan_duplicates_job()` → publishes TaskType.SCAN_DUPLICATES to Redis
  - Every 15 min: `scan_sla_job()` → publishes TaskType.SCAN_SLA
  - Every 60 min: `scan_licenses_job()` → publishes TaskType.SCAN_LICENSES
  - Every 60 min: `reconcile_job()` → publishes TaskType.RECONCILE
  - Every 48h: `auto_release_holds_job()` → calls payment_handler.auto_release_stale_holds()

#### `backend/agents/base_agent.py`
- `BaseAgent` abstract class
  - `__init__(self, db, name: AgentName, model: ModelName)`
  - `async run(task: AgentTask) -> AgentResult` — abstract
  - `async _infer(prompt, severity, system_prompt, expect_json)` — wraps llm_router.infer()
  - `_elapsed_ms()` — timing helper
  - `async _write_audit(pipeline_result: PipelineResult)` — calls audit_agent

#### `backend/agents/orchestrator.py`
- `OrchestratorAgent`
- `async run(task: AgentTask) -> PipelineResult`
- Implements blueprint §2C data flow (10 steps):
  1. Dequeue task from Redis
  2. Dispatch to AnomalyDetectionAgent
  3. For each DetectionResult: if needs_deep_reasoning → invoke DecisionAgent
  4. Pass decision to ActionExecutionAgent
  5. Call AuditAgent with full PipelineResult
  6. Return PipelineResult
- `route_model(task)` — calls `llm_router.select_model()` with task severity
- Runs as background asyncio task, consuming Redis queue continuously

#### `backend/agents/anomaly_detection.py`
- `AnomalyDetectionAgent`
- `async scan_duplicates(db) -> list[DetectionResult]` — blueprint §6A algorithm
  - Query window: vendor_id + amount ±2% + 30 days
  - Confidence tiers: same PO=0.97, similar invoice=0.82, amount+vendor=0.65
  - Use `levenshtein()` from core.utils for fuzzy invoice matching
  - Use `fingerprint_transaction()` for fast pre-filter
- `async scan_sla(db) -> list[DetectionResult]` — blueprint §6C
  - Call `get_at_risk_tickets()` from sla_handler
  - For each: compute `sla_breach_probability()` from core.utils
  - Update breach_prob column via `update_breach_probability()`
  - Flag if P(breach) >= SLA_ESCALATION_THRESHOLD (0.70)
- `async scan_licenses(db) -> list[DetectionResult]` — blueprint §6B
  - Call `get_unused_licenses()` from license_handler
  - Confidence: 0.99 if employee_active=False, 0.75 if inactive>60d, 0.50 if inactive>30d
- `async scan_pricing(db) -> list[DetectionResult]`
  - Compare transaction amount vs vendor.market_benchmark
  - Flag if >15% above benchmark (PRICING_ANOMALY_PCT)
- `async run(task: AgentTask) -> list[DetectionResult]`
  - Routes to correct scan method based on task.task_type

#### `backend/agents/decision_agent.py`
- `DecisionAgent` — wraps deepseek-r1:7b
- `async reason(detection: DetectionResult, context: dict) -> DecisionResult`
- Builds prompt from blueprint §7 template:
  ```
  SYSTEM: You are a financial risk reasoning agent. Analyze anomalies precisely.
          Output ONLY structured JSON. No explanation outside JSON.
  USER:   Anomaly data: {anomaly_json}
          Historical context: {vendor_history}
          Identify root_cause, confidence, action, cost_impact_inr, urgency, reasoning_chain
  ```
- Calls `llm_router.infer(prompt, severity=HIGH, expect_json=True)`
- Parses DecisionOutput schema — handles malformed JSON gracefully with fallback
- Returns `DecisionResult` with full reasoning_chain preserved
- Gate: only called when `detection.needs_deep_reasoning` is True

#### `backend/agents/action_execution.py`
- `ActionExecutionAgent`
- `async execute(decision: DecisionResult, anomaly_id: UUID, db) -> ActionResult`
- Approval gate: `if requires_approval(decision.cost_impact_inr): → enqueue_for_approval()`
- Action dispatch table (mirrors blueprint §8):
  - `hold_payment` → `payment_handler.hold_payment()`
  - `license_deactivated` → `license_handler.deactivate_license()` or `bulk_deactivate_licenses()`
  - `sla_escalation` → `sla_handler.escalate_ticket()` + `notify_sla_escalation()`
  - `email_sent` → `notification_handler.send_alert_email()`
  - `vendor_renegotiation_flag` → insert task record in DB
- After each action: persist to `actions_taken` table
- Build `rollback_payload` for every action (enables override flow)

#### `backend/agents/audit_agent.py`
- `AuditAgent`
- `async log(pipeline_result: PipelineResult, db) -> str` — returns audit_id
- Writes one `audit_trail` record per pipeline run using `generate_audit_id()`
- Schema: matches blueprint §10 exactly — all fields including reasoning_invoked,
  reasoning_model, reasoning_output, approval_status
- `async get_audit_trail(db, limit, type_filter) -> list[dict]`
- `async get_audit_record(db, audit_id) -> dict`
- `async override_audit(db, audit_id, reason) -> dict` — human override endpoint

#### `backend/agents/fallback_agent.py`
- `FallbackAgent`
- Called when any other agent raises an exception or times out
- Uses `llama3.2:3b` always
- `async handle_error(error: Exception, task: AgentTask) -> AgentResult`
- Logs error, writes minimal audit record, returns safe failure result
- Does NOT propagate exceptions — the pipeline must always complete

### Phase 2 Routers to create

#### `backend/routers/anomalies.py`
- `GET /api/anomalies/` — list with filters: status, severity, type, limit, offset
- `GET /api/anomalies/{id}` — full detail + related actions
- `GET /api/anomalies/stats` — counts by type and severity (dashboard feed)
- `POST /api/anomalies/{id}/dismiss` — mark as dismissed with reason
- `PATCH /api/anomalies/{id}/status` — update status

#### `backend/routers/actions.py`
- `GET /api/actions/` — list with filters: status, action_type, limit
- `GET /api/actions/{id}` — full detail including rollback_payload
- `POST /api/actions/{id}/rollback` — manual rollback (calls approval_service.override_action)

#### `backend/routers/audit.py`
- `GET /api/audit/` — paginated audit trail, filter by type
- `GET /api/audit/{audit_id}` — full audit record with reasoning chain
- `GET /api/audit/summary?period=month` — aggregated stats
- `POST /api/audit/{audit_id}/override` — human override with reason

#### `backend/routers/savings.py`
- `GET /api/savings/summary` — SavingsSummary (drives the live counter)
- `GET /api/savings/breakdown` — per-category with formulas shown
- `GET /api/savings/projection` — monthly + annual projection

### Phase 2 Tests to add

#### `backend/tests/test_agents.py`
- Test OrchestratorAgent routes to correct sub-agent
- Test AnomalyDetectionAgent.scan_duplicates() finds the 3 seeded pairs
- Test AnomalyDetectionAgent.scan_sla() flags the 5 near-breach tickets
- Test AnomalyDetectionAgent.scan_licenses() flags 29 terminated + 40 inactive
- Test DecisionAgent parses deepseek JSON output correctly
- Test FallbackAgent handles exceptions without propagating

#### `backend/tests/test_pipeline.py`
- End-to-end test: inject duplicate transaction → pipeline → verify payment held
- End-to-end test: SLA ticket at 82% → pipeline → verify escalated
- Verify audit_trail record written with full reasoning chain
- Verify cost_saved recorded correctly in actions_taken

---

## ═══════════════════════════════════════════════════
## PHASE 3 — Integration & Scheduling
## ═══════════════════════════════════════════════════

**Goal:** Wire all agents together through Redis, activate APScheduler, implement cost calculation service, and expose all savings endpoints. By end of Phase 3, the system runs autonomously on a 15-minute cycle.

### Key implementation points

**Redis queue consumer loop** in `orchestrator.py`:
```python
async def consume_forever(self):
    """Run as background asyncio task — processes Redis queue continuously."""
    async for task in redis_client.consume_tasks():
        try:
            result = await self.run(task)
            await redis_client.publish_result(result.to_summary())
        except Exception as e:
            await self.fallback_agent.handle_error(e, task)
```

**Start consumer in `main.py` lifespan:**
```python
# After Redis init:
orchestrator = OrchestratorAgent(...)
asyncio.create_task(orchestrator.consume_forever())
```

**APScheduler jobs** publish to Redis, they don't call agents directly:
```python
async def scan_duplicates_job():
    task = AgentTask(task_id=str(uuid4()), task_type=TaskType.SCAN_DUPLICATES)
    await redis_client.publish_task(task)
```

**Cost calculator** queries only `status='success'` actions — pending approvals never count as saved.

**`GET /api/savings/summary` response shape** (drives dashboard counter):
```json
{
  "duplicate_payments_blocked": 147000,
  "unused_subscriptions_cancelled": 87000,
  "sla_penalties_avoided": 65000,
  "reconciliation_errors_fixed": 32400,
  "total_savings_this_month": 331400,
  "annual_projection": 3976800,
  "actions_taken_count": 12,
  "anomalies_detected_count": 18,
  "pending_approvals_count": 2
}
```

---

## ═══════════════════════════════════════════════════
## PHASE 4 — Next.js Frontend
## ═══════════════════════════════════════════════════

**Goal:** Build the complete dashboard with 6 components, dark theme, real-time polling every 10 seconds, and the demo trigger button.

### Frontend structure to create

```
frontend/
├── Dockerfile               — node:20-alpine, npm run build, port 3000
├── package.json             — next@14, tailwindcss, lucide-react, axios
├── next.config.js           — rewrites: /api/* → http://backend:8000/api/*
├── tailwind.config.js       — dark mode: 'class', custom colors
├── app/
│   ├── layout.tsx           — dark theme root, global styles, nav bar
│   ├── page.tsx             — main dashboard, orchestrates all components
│   └── globals.css          — Tailwind directives + custom CSS vars
└── components/
    ├── SavingsCounter.tsx   — animated ₹ counter, updates every 10s
    │                          Shows: total, duplicate, subscription, SLA, reconciliation
    ├── AnomalyFeed.tsx      — live feed of detections, color-coded by severity
    │                          Columns: type, severity badge, confidence, cost impact, time
    ├── ActionsPanel.tsx     — executed/pending/failed actions with status badges
    │                          Shows model used (qwen vs deepseek), elapsed time
    ├── AuditTrail.tsx       — full audit trail table with expandable reasoning chains
    │                          DeepSeek reasoning_chain shown as numbered steps
    ├── ApprovalQueue.tsx    — pending approvals with Approve/Reject buttons
    │                          Shows cost impact, calls POST /api/approvals/{id}/approve
    ├── DemoTrigger.tsx      — "Simulate Cost Leak" button
    │                          Injects synthetic anomaly, shows real-time pipeline progress
    └── ModelStatus.tsx      — header component: which model is loaded, deepseek budget
```

### Dashboard design spec
- **Dark theme** — background #0a0a0a, cards #111111, borders #222222
- **Color coding:** CRITICAL=red, HIGH=orange, MEDIUM=yellow, LOW=blue
- **Live savings counter** — large typography, animates when value changes, Indian number format (₹3,31,400)
- **Polling:** `setInterval` every 10,000ms for savings + anomalies + actions
- **No WebSocket needed** — REST polling is sufficient and simpler for hackathon

### Key API calls from frontend
```typescript
GET  /api/savings/summary           → SavingsCounter
GET  /api/anomalies/?limit=20       → AnomalyFeed
GET  /api/actions/?limit=20         → ActionsPanel
GET  /api/audit/?limit=50           → AuditTrail
GET  /api/approvals/                → ApprovalQueue
POST /api/approvals/{id}/approve    → ApprovalQueue approve button
POST /api/approvals/{id}/reject     → ApprovalQueue reject button
POST /api/approvals/{id}/override   → AuditTrail override button
POST /api/demo/trigger              → DemoTrigger button
GET  /api/system/status             → ModelStatus header
```

---

## ═══════════════════════════════════════════════════
## PHASE 5 — Demo Polish
## ═══════════════════════════════════════════════════

**Goal:** Demo trigger, fallback video prep, final validation of all cost calculations.

### `backend/routers/demo.py`
`POST /api/demo/trigger` — the "Simulate Cost Leak" button

```python
# Injects a pre-scripted scenario into the live system:
# 1. Insert a duplicate payment pair (₹1,00,000, same PO)
# 2. Publish TaskType.DEMO_TRIGGER to Redis with scenario metadata
# 3. Orchestrator processes it at HIGH priority
# 4. Returns task_id — frontend polls for result
# 5. Full pipeline runs: detect → deepseek reason → hold payment → audit
# Target elapsed time: 5-8 seconds
```

`GET /api/demo/status/{task_id}` — poll for pipeline completion

`POST /api/demo/reset` — calls reset_demo.sh equivalent in Python (truncate + reseed)

### Demo scenarios (blueprint §14)

**Scenario 1 — Duplicate Payment (primary demo)**
- Inject: Vendor ABC, ₹1,00,000, same PO as existing approved transaction
- Expected: Detected in <2s, deepseek reasons, payment held, email sent, audit written
- Dashboard: savings counter increments by ₹1,00,000 live

**Scenario 2 — SLA Near-Breach**
- Inject: Ticket TKT-DEMO-001, P1, 4h SLA, opened 3.3h ago, no assignee
- Expected: P(breach)=~0.85, escalated, email sent
- Dashboard: anomaly feed shows new entry, actions panel shows escalation

**Scenario 3 — Unused Subscriptions**
- Inject: 5 licenses for non-existent employees
- Expected: All 5 deactivated, ₹15,000/month saved shown
- Dashboard: actions panel shows bulk deactivation

**Scenario 4 — Approval Queue Demo**
- Inject: Duplicate payment of ₹75,000 (above ₹50,000 auto-approve limit)
- Expected: Goes to approval queue, NOT auto-executed
- Demo: Presenter clicks Approve in UI → action executes live

### 3-Minute Pitch Structure (blueprint §14)

| Time | Action | Message |
|---|---|---|
| 0:00–0:30 | Show live dashboard with ₹3,31,400 counter | "Not reports. Money." |
| 0:30–1:15 | Click Simulate → duplicate detected live | "AI detects and ACTS in 6 seconds" |
| 1:15–2:00 | SLA escalation + audit trail | "Full audit trail for compliance" |
| 2:00–2:30 | License deactivation, 29 cancelled | "₹87,000/month. Every month." |
| 2:30–3:00 | Scroll audit log, show deepseek reasoning | "Every decision is explainable" |

**Opening line:** *"Indian enterprises lose ₹40 crore/year to preventable cost leakage."*
**Closing line:** *"At this rate: ₹39 lakhs saved per year, autonomously."*

---

## Key Design Decisions Already Made

1. **No cloud APIs** — 100% local inference via Ollama. No data leaves the enterprise.
2. **Approval gate at ₹50,000** — `requires_approval()` in `approval_service.py`
3. **Override = rollback** — `override_action()` calls the right handler's rollback method and writes an override audit entry. Blueprint §11A.
4. **ActionState enum** — PENDING → PENDING_APPROVAL → APPROVED → SUCCESS, or REJECTED/OVERRIDDEN/ROLLED_BACK. All states in `core/constants.py`.
5. **One audit record per pipeline run** — written by AuditAgent after all steps complete. Contains: input_data, detection, reasoning_invoked, reasoning_model, reasoning_output, action_taken, cost_impact_inr, approval_status.
6. **deepseek <think> tags stripped** — `_extract_json()` in `llm_router.py` removes `<think>...</think>` before JSON parsing.
7. **Redis TTL 30min** — all task keys expire. Max 5 concurrent Ollama workers. Blueprint §12.
8. **Seed data is deterministic** — 3 duplicate pairs on PO-2891/3042/4117, 29 terminated licenses, 5 near-breach tickets. Always same starting state for demo.

---

## Cost Impact Formulas (Blueprint §9 — Judges check these)

```python
# Formula 1: Duplicate Payment Savings
cost_saved = SUM(held_invoice.amount FOR held_invoice IN duplicate_invoices)

# Formula 2: Unused Subscription Savings
monthly_savings = SUM(lic.monthly_cost FOR lic IN deactivated_licenses)
annual_projection = monthly_savings * 12

# Formula 3: SLA Penalty Prevention
penalty_avoided = SUM(ticket.penalty_amount
    FOR ticket IN escalated_tickets
    WHERE ticket.final_status == 'resolved_before_breach')

# Formula 4: Projected Annual Savings
total_monthly = duplicate_avg + subscription_savings + sla_avg + reconciliation_avg
projected_annual = total_monthly * 12
roi_percent = (projected_annual / system_cost) * 100
```

**Sample dashboard numbers to match:**
- Duplicate payments blocked: ₹1,47,000/month → ₹17,64,000/year
- Unused subscriptions: ₹87,000/month → ₹10,44,000/year
- SLA penalties avoided: ₹65,000/month → ₹7,80,000/year
- Reconciliation errors: ₹32,400/month → ₹3,88,800/year
- **TOTAL: ₹3,31,400/month → ₹39,76,800/year**

---

## Common Pitfalls & Solutions

| Problem | Solution |
|---|---|
| Two 7B models loaded simultaneously → OOM | `_ensure_model_loaded()` in llm_router.py calls `_ollama_unload()` first |
| deepseek outputs `<think>` tags before JSON | `_extract_json()` strips them with regex |
| asyncpg JSONB columns reject Python dicts with Decimal/UUID | `safe_jsonable()` in core/utils.py converts all types |
| SLA deadline column — can't query before it exists | It's a GENERATED column in schema.sql: `opened_at + (sla_hours * INTERVAL '1 hour')` |
| Approval actions double-executing | Check `status='pending_approval'` before `approve_action()`, raises ValueError if wrong state |
| Redis consumer blocking event loop | Use `await asyncio.sleep(0)` between iterations, or run consumer in `asyncio.create_task()` |
| uvicorn reload volume mount on Windows | `./backend:/app` in docker-compose.yml — edits sync automatically, no rebuild needed |

---

## How to Run After Handoff

```powershell
# 1. Start infrastructure
cd cost-intelligence
docker compose up -d postgres redis mailhog

# 2. Verify backend is up
docker compose up -d backend
docker compose logs -f backend
# Should see: "Ready → http://localhost:8000/docs"

# 3. Check models are pulled
ollama list
# Should show: qwen2.5:7b, deepseek-r1:7b, llama3.2:3b

# 4. Test the system
curl http://localhost:8000/health
curl http://localhost:8000/api/system/status
curl http://localhost:8000/api/savings/summary   # (after Phase 3)

# 5. Reset demo data anytime
./scripts/reset_demo.sh --confirm

# 6. Check everything
./scripts/check_health.sh
```

---

## Handoff Prompt for New Chat

If continuing in a new Claude session, use this as your opening message:

```
I am building the Self-Healing Enterprise Cost Intelligence System for ET Gen AI Hackathon 2026.
Phase 1 is complete and running. Please read the ROADMAP.md file I'm attaching and continue
with Phase 2 — building all 6 agents (Orchestrator, AnomalyDetection, Decision, ActionExecution,
Audit, Fallback), Redis client, APScheduler, cost calculator, and Phase 2 routers.

Key context:
- Stack: FastAPI + asyncpg + Redis + Ollama (local LLMs) + Next.js 14
- All core/ files exist: config.py, constants.py, utils.py
- All action_handlers/ exist: payment, license, sla, notification
- interfaces.py exists: AgentResult, DetectionResult, DecisionResult, ActionResult
- llm_router.py exists with full routing + model swap logic
- approval_service.py exists with full approval/override flow
- DB schema has all 8 tables including approval_queue and audit_trail
- Seed data: 3 duplicate pairs (PO-2891/3042/4117), 29 terminated licenses, 5 near-breach tickets
- Model routing: LOW→llama3.2:3b, HIGH/CRITICAL→deepseek-r1:7b, else→qwen2.5:7b
- Auto-approve limit: ₹50,000
- Docker: postgres/redis/mailhog in containers, ollama native on Windows host
- Backend volume-mounted, uvicorn --reload, no rebuild needed for .py changes

Start with backend/agents/base_agent.py, then orchestrator.py, then anomaly_detection.py,
then decision_agent.py, action_execution.py, audit_agent.py, fallback_agent.py,
then services/redis_client.py, services/cost_calculator.py, services/scheduler.py,
then routers/anomalies.py, routers/actions.py, routers/audit.py, routers/savings.py.
Generate complete, production-ready code for each file.
```

---

*ET Gen AI Hackathon 2026 — Problem Statement #3 — Prize Pool: ₹10,00,000*
