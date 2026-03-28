#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# check_health.sh — Verify all services are up and responsive.
#
# Checks: PostgreSQL, Redis, Ollama (+ models loaded), FastAPI, Next.js,
#         MailHog, and the full agent pipeline status.
#
# Usage:
#   ./scripts/check_health.sh
#   ./scripts/check_health.sh --json    # machine-readable output
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if [ -f .env ]; then
    set -o allexport; source .env; set +o allexport
fi

BACKEND="${BACKEND_URL:-http://localhost:8000}"
FRONTEND="${FRONTEND_URL:-http://localhost:3000}"
OLLAMA="${OLLAMA_HOST:-http://localhost:11434}"
MAILHOG="${MAILHOG_URL:-http://localhost:8025}"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-cost_intelligence}"
PGUSER="${POSTGRES_USER:-ci_user}"
export PGPASSWORD="${POSTGRES_PASSWORD:-ci_pass}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

JSON_MODE=false
[[ "${1:-}" == "--json" ]] && JSON_MODE=true

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'
PASS="${GREEN}✓${RESET}"
FAIL="${RED}✗${RESET}"
WARN="${YELLOW}⚠${RESET}"

declare -A RESULTS
ALL_OK=true

check() {
    local name="$1"
    local cmd="$2"
    local detail="${3:-}"

    if eval "$cmd" > /dev/null 2>&1; then
        RESULTS["$name"]="ok"
        printf "  %b  %-28s %b\n" "$PASS" "$name" "${CYAN}${detail}${RESET}"
    else
        RESULTS["$name"]="fail"
        ALL_OK=false
        printf "  %b  %-28s %b\n" "$FAIL" "$name" "${RED}unreachable${RESET}"
    fi
}

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo -e "${CYAN}  Cost Intelligence — Health Check                ${RESET}"
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo ""
echo "  Infrastructure:"

# ── PostgreSQL ────────────────────────────────────────────────────────────────
PG_CMD="psql -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE -c 'SELECT 1' -t -q"
check "PostgreSQL" "$PG_CMD" "${PGHOST}:${PGPORT}/${PGDATABASE}"

# ── Redis ─────────────────────────────────────────────────────────────────────
check "Redis" "redis-cli -h $REDIS_HOST -p $REDIS_PORT ping | grep -q PONG" \
    "${REDIS_HOST}:${REDIS_PORT}"

# ── MailHog ───────────────────────────────────────────────────────────────────
check "MailHog (SMTP)" "curl -sf ${MAILHOG}/api/v2/messages" \
    "${MAILHOG}"

echo ""
echo "  LLM Layer:"

# ── Ollama ────────────────────────────────────────────────────────────────────
check "Ollama API" "curl -sf ${OLLAMA}/api/tags" "${OLLAMA}"

# Check each model is pulled
for model in "qwen2.5:7b" "deepseek-r1:7b" "llama3.2:3b"; do
    label="  Model: ${model}"
    if curl -sf "${OLLAMA}/api/tags" 2>/dev/null | grep -q "$model"; then
        printf "  %b  %-28s %b\n" "$PASS" "$label" "${GREEN}pulled${RESET}"
    else
        printf "  %b  %-28s %b\n" "$WARN" "$label" "${YELLOW}not pulled — run scripts/pull_models.sh${RESET}"
        ALL_OK=false
    fi
done

echo ""
echo "  Application:"

# ── FastAPI Backend ───────────────────────────────────────────────────────────
check "FastAPI /health" "curl -sf ${BACKEND}/health" "${BACKEND}"

# ── System status endpoint ────────────────────────────────────────────────────
if curl -sf "${BACKEND}/api/system/status" > /dev/null 2>&1; then
    STATUS=$(curl -sf "${BACKEND}/api/system/status")
    PENDING=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pending_approvals',0))" 2>/dev/null || echo "?")
    DEEPSEEK_CALLS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['models'][1].get('calls_this_hour',0))" 2>/dev/null || echo "?")
    printf "  %b  %-28s %b\n" "$PASS" "System status API" \
        "${CYAN}pending_approvals=${PENDING} deepseek_calls=${DEEPSEEK_CALLS}${RESET}"
fi

# ── Next.js Frontend ──────────────────────────────────────────────────────────
check "Next.js dashboard" "curl -sf -o /dev/null -w '%{http_code}' ${FRONTEND} | grep -q 200" \
    "${FRONTEND}"

echo ""

# ── DB table row counts ───────────────────────────────────────────────────────
echo "  Data:"
if psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -c 'SELECT 1' -t -q > /dev/null 2>&1; then
    COUNTS=$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -t -q <<-SQL
        SELECT
            (SELECT COUNT(*) FROM transactions)   AS txn,
            (SELECT COUNT(*) FROM licenses)       AS lic,
            (SELECT COUNT(*) FROM sla_metrics)    AS sla,
            (SELECT COUNT(*) FROM anomaly_logs)   AS anom,
            (SELECT COUNT(*) FROM actions_taken)  AS acts,
            (SELECT COUNT(*) FROM audit_trail)    AS audit;
SQL
    )
    read -r txn lic sla anom acts audit <<< "$(echo "$COUNTS" | tr '|' ' ')"
    printf "  %b  %-28s %b\n" "·" "transactions"  "${txn// /} rows"
    printf "  %b  %-28s %b\n" "·" "licenses"      "${lic// /} rows"
    printf "  %b  %-28s %b\n" "·" "sla_metrics"   "${sla// /} rows"
    printf "  %b  %-28s %b\n" "·" "anomaly_logs"  "${anom// /} rows"
    printf "  %b  %-28s %b\n" "·" "actions_taken" "${acts// /} rows"
    printf "  %b  %-28s %b\n" "·" "audit_trail"   "${audit// /} rows"
fi

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
if $ALL_OK; then
    echo -e "${GREEN}  All systems operational.${RESET}"
else
    echo -e "${RED}  Some services are down. Check docker compose ps${RESET}"
    echo "  docker compose logs <service>"
fi
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo ""

$ALL_OK