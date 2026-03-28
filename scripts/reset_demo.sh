#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# reset_demo.sh — Wipe all data and re-seed the demo dataset.
#
# Use before a demo run to get a clean, deterministic starting state.
# Blueprint §14 Backup Plan: "Keep a JSON fixture file that re-seeds
# demo data in 3 seconds."
#
# Usage:
#   ./scripts/reset_demo.sh           # uses .env defaults
#   ./scripts/reset_demo.sh --confirm # skip the confirmation prompt
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Load env ──────────────────────────────────────────────────────────────────
if [ -f .env ]; then
    set -o allexport
    source .env
    set +o allexport
fi

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-cost_intelligence}"
PGUSER="${POSTGRES_USER:-ci_user}"
PGPASSWORD="${POSTGRES_PASSWORD:-ci_pass}"
export PGPASSWORD

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
echo -e "${YELLOW}  Cost Intelligence — Demo Reset                  ${RESET}"
echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
echo ""

# ── Confirmation ──────────────────────────────────────────────────────────────
if [[ "${1:-}" != "--confirm" ]]; then
    echo -e "  ${RED}WARNING: This will DELETE all data in ${PGDATABASE}${RESET}"
    echo -e "  Database: ${PGHOST}:${PGPORT}/${PGDATABASE}"
    echo ""
    read -r -p "  Type 'reset' to confirm: " confirm
    if [[ "$confirm" != "reset" ]]; then
        echo "  Aborted."
        exit 0
    fi
    echo ""
fi

# ── Truncate all tables ───────────────────────────────────────────────────────
echo -n "  Truncating all tables ... "

psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" <<-SQL
    TRUNCATE TABLE
        audit_trail,
        actions_taken,
        approval_queue,
        anomaly_logs,
        sla_metrics,
        licenses,
        transactions,
        vendors
    RESTART IDENTITY CASCADE;
SQL

echo -e "${GREEN}✓${RESET}"

# ── Re-seed ───────────────────────────────────────────────────────────────────
echo -n "  Re-seeding demo data ... "

# Run via Docker if backend container is running, else run directly
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "ci_backend"; then
    docker exec ci_backend python db/seed_data.py
else
    (cd backend && python db/seed_data.py)
fi

echo -e "${GREEN}✓${RESET}"
echo ""
echo -e "${GREEN}  Demo data restored:${RESET}"
echo "    ✓  ~456 transactions (incl. 3 duplicate payment pairs)"
echo "    ✓  200 licenses (29 terminated employees, 40 inactive)"
echo "    ✓  50 SLA tickets (5 near-breach, no assignee)"
echo "    ✓  Audit trail cleared"
echo "    ✓  Approval queue cleared"
echo ""
echo -e "${CYAN}  Ready for demo.${RESET} Dashboard: http://localhost:3000"
echo -e "${YELLOW}══════════════════════════════════════════════════${RESET}"
echo ""