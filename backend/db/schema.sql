-- ═══════════════════════════════════════════════════════════════════════════
-- Self-Healing Enterprise Cost Intelligence System
-- Database Schema — PostgreSQL 16
-- ═══════════════════════════════════════════════════════════════════════════

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- for fuzzy vendor name matching

-- ─── vendors ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendors (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200) NOT NULL,
    category        VARCHAR(100) NOT NULL DEFAULT 'Services',  -- SaaS | Infrastructure | Services
    contract_rate   DECIMAL(10,2),
    payment_terms   INTEGER DEFAULT 30,   -- days
    risk_score      FLOAT DEFAULT 0.0,    -- 0.0 to 1.0
    market_benchmark DECIMAL(10,2),       -- benchmark rate for pricing anomaly detection
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ─── transactions ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vendor_id        UUID REFERENCES vendors(id),
    invoice_number   VARCHAR(100) NOT NULL,
    amount           DECIMAL(12,2) NOT NULL,
    currency         CHAR(3) DEFAULT 'INR',
    transaction_date DATE NOT NULL,
    po_number        VARCHAR(50),
    status           VARCHAR(20) DEFAULT 'pending',  -- pending | approved | held | disputed
    hold_reason      TEXT,
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

-- ─── licenses ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS licenses (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tool_name        VARCHAR(100) NOT NULL,           -- Slack | Jira | Zoom | etc.
    assigned_user_id UUID,
    assigned_email   VARCHAR(200),
    last_login       TIMESTAMP,
    is_active        BOOLEAN DEFAULT TRUE,
    monthly_cost     DECIMAL(10,2) NOT NULL,
    employee_active  BOOLEAN DEFAULT TRUE,            -- synced from HR system
    deactivated_at   TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ─── sla_metrics ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sla_metrics (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id        VARCHAR(50) UNIQUE NOT NULL,
    sla_hours        INTEGER NOT NULL,
    opened_at        TIMESTAMP NOT NULL,
    sla_deadline     TIMESTAMP GENERATED ALWAYS AS (opened_at + (sla_hours * INTERVAL '1 hour')) STORED,
    resolved_at      TIMESTAMP,
    status           VARCHAR(20) DEFAULT 'open',  -- open | resolved | breached | escalated
    assignee_id      UUID,
    priority         VARCHAR(10) DEFAULT 'P2',    -- P1 | P2 | P3
    penalty_amount   DECIMAL(10,2) DEFAULT 0.00,
    breach_prob      FLOAT DEFAULT 0.0,           -- updated by SLA agent
    escalated_at     TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW()
);

-- ─── anomaly_logs ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomaly_logs (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    anomaly_type     VARCHAR(50) NOT NULL,  -- duplicate | unused_subscription | sla_risk | reconciliation_gap | pricing_anomaly | infra_waste
    entity_id        UUID,                  -- references relevant entity (txn, license, ticket, etc.)
    entity_table     VARCHAR(50),           -- which table entity_id refers to
    confidence       FLOAT NOT NULL,        -- 0.0 to 1.0
    severity         VARCHAR(10) NOT NULL,  -- LOW | MEDIUM | HIGH | CRITICAL
    detected_at      TIMESTAMP DEFAULT NOW(),
    reasoning        TEXT,                  -- deepseek-r1 output if invoked
    root_cause       TEXT,
    model_used       VARCHAR(50),
    cost_impact_inr  DECIMAL(12,2) DEFAULT 0.00,
    status           VARCHAR(20) DEFAULT 'detected',  -- detected | actioned | resolved | dismissed | overridden
    override_reason  TEXT,
    overridden_by    VARCHAR(100),
    overridden_at    TIMESTAMP
);

-- ─── actions_taken ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS actions_taken (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    anomaly_id       UUID REFERENCES anomaly_logs(id),
    action_type      VARCHAR(50) NOT NULL,  -- payment_hold | email_sent | license_deactivated | sla_escalation | vendor_flag | resource_downsize
    executed_at      TIMESTAMP DEFAULT NOW(),
    executed_by      VARCHAR(50) NOT NULL,  -- agent name
    cost_saved       DECIMAL(12,2) DEFAULT 0.00,
    status           VARCHAR(30) DEFAULT 'success',  -- success | failed | pending_approval | approved | rejected | rolled_back
    approval_required BOOLEAN DEFAULT FALSE,
    approved_by      VARCHAR(100),
    approval_timestamp TIMESTAMP,
    rejection_reason TEXT,
    payload          JSONB,                -- full action details
    rollback_payload JSONB,               -- data needed to reverse the action
    rolled_back_at   TIMESTAMP
);

-- ─── approval_queue ───────────────────────────────────────────────────────────
-- Mirrors actions_taken for high-cost items awaiting sign-off.
-- Separate table keeps the approval workflow queryable independently.
CREATE TABLE IF NOT EXISTS approval_queue (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action_id        UUID REFERENCES actions_taken(id) ON DELETE CASCADE,
    anomaly_id       UUID REFERENCES anomaly_logs(id),
    action_type      VARCHAR(50) NOT NULL,
    cost_impact_inr  DECIMAL(12,2) NOT NULL,
    requested_by     VARCHAR(50) NOT NULL,   -- agent that requested approval
    requested_at     TIMESTAMP DEFAULT NOW(),
    status           VARCHAR(20) DEFAULT 'pending',  -- pending | approved | rejected | expired
    reviewed_by      VARCHAR(100),
    reviewed_at      TIMESTAMP,
    review_note      TEXT,
    expires_at       TIMESTAMP,             -- auto-expire stale requests
    payload          JSONB                  -- snapshot of action details
);

CREATE INDEX IF NOT EXISTS idx_approval_queue_status
    ON approval_queue (status, requested_at DESC)
    WHERE status = 'pending';

-- ─── audit_trail ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_trail (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id         VARCHAR(50) UNIQUE NOT NULL,  -- human-readable: aud-YYYYMMDD-NNN
    timestamp        TIMESTAMP DEFAULT NOW(),
    agent            VARCHAR(50) NOT NULL,
    model_used       VARCHAR(50),
    input_data       JSONB,
    detection        JSONB,
    reasoning_invoked BOOLEAN DEFAULT FALSE,
    reasoning_model  VARCHAR(50),
    reasoning_output JSONB,
    action_taken     JSONB,
    cost_impact_inr  DECIMAL(12,2) DEFAULT 0.00,
    approval_status  VARCHAR(20),
    approved_by      VARCHAR(100),
    approval_timestamp TIMESTAMP,
    final_status     VARCHAR(30) NOT NULL DEFAULT 'actioned',
    override_reason  TEXT,
    reversed_action  VARCHAR(50)
);

-- ═══════════════════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════════════════

-- transactions: core duplicate detection query
CREATE INDEX IF NOT EXISTS idx_txn_vendor_date_amount
    ON transactions (vendor_id, transaction_date, amount);

CREATE INDEX IF NOT EXISTS idx_txn_po_number
    ON transactions (po_number)
    WHERE po_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_txn_status
    ON transactions (status);

-- sla_metrics: breach prediction polling
CREATE INDEX IF NOT EXISTS idx_sla_status_deadline
    ON sla_metrics (status, sla_deadline)
    WHERE status = 'open';

-- anomaly_logs: dashboard feed
CREATE INDEX IF NOT EXISTS idx_anomaly_detected_at
    ON anomaly_logs (detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_status_severity
    ON anomaly_logs (status, severity);

-- actions_taken: approval queue
CREATE INDEX IF NOT EXISTS idx_actions_approval
    ON actions_taken (status, approval_required)
    WHERE approval_required = TRUE;

-- audit_trail: audit viewer
CREATE INDEX IF NOT EXISTS idx_audit_timestamp
    ON audit_trail (timestamp DESC);

-- licenses: unused subscription scan
CREATE INDEX IF NOT EXISTS idx_license_active_login
    ON licenses (is_active, last_login)
    WHERE is_active = TRUE;

-- ═══════════════════════════════════════════════════════════════════════════
-- HELPER FUNCTION: auto-update updated_at
-- ═══════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_transactions_updated_at ON transactions;
CREATE TRIGGER update_transactions_updated_at
    BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();