#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# pull_models.sh — Pull all 3 Ollama models required by the system.
#
# Usage:
#   ./scripts/pull_models.sh                  # uses localhost:11434
#   OLLAMA_HOST=http://myhost:11434 ./scripts/pull_models.sh
#
# Blueprint §13 Phase 1, Step 1:
#   ollama pull qwen2.5:7b
#   ollama pull deepseek-r1:7b
#   ollama pull llama3.2:3b
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
OLLAMA_BIN="${OLLAMA_BIN:-ollama}"

MODELS=(
    "qwen2.5:7b      # DEFAULT — all standard ops, anomaly detection, action execution"
    "deepseek-r1:7b  # REASONING — HIGH/CRITICAL severity root cause analysis"
    "llama3.2:3b     # FALLBACK — error recovery, trivial log entries"
)

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo -e "${CYAN}  Cost Intelligence — Ollama Model Pull           ${RESET}"
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo ""

# Check Ollama is reachable
echo -n "  Checking Ollama at ${OLLAMA_HOST} ... "
if ! curl -sf "${OLLAMA_HOST}/api/tags" > /dev/null 2>&1; then
    echo -e "${RED}✗ unreachable${RESET}"
    echo ""
    echo -e "  ${YELLOW}Start Ollama first:${RESET}"
    echo "    docker compose up -d ollama"
    echo "    # or: ollama serve"
    echo ""
    exit 1
fi
echo -e "${GREEN}✓ online${RESET}"
echo ""

# Pull each model
FAILED=()
for model_line in "${MODELS[@]}"; do
    model=$(echo "$model_line" | awk '{print $1}')
    comment=$(echo "$model_line" | sed 's/^[^ ]* *//')

    echo -e "  ${CYAN}Pulling ${model}${RESET}"
    echo -e "  ${comment}"
    echo ""

    if "${OLLAMA_BIN}" pull "$model"; then
        echo -e "  ${GREEN}✓ ${model} ready${RESET}"
    else
        echo -e "  ${RED}✗ ${model} failed${RESET}"
        FAILED+=("$model")
    fi
    echo ""
done

# Summary
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
if [ ${#FAILED[@]} -eq 0 ]; then
    echo -e "${GREEN}  All models pulled successfully.${RESET}"
    echo ""
    echo "  Memory budget check:"
    echo "    qwen2.5:7b   ~5.5 GB  (default)"
    echo "    deepseek-r1  ~5.5 GB  (swapped in for HIGH severity)"
    echo "    llama3.2:3b  ~2.5 GB  (always resident as fallback)"
    echo "    Peak usage:  ~13.5 GB (during model swap) ✓ safe on 16GB"
else
    echo -e "${RED}  Failed: ${FAILED[*]}${RESET}"
    echo "  Re-run this script or: ollama pull <model>"
    exit 1
fi
echo -e "${CYAN}══════════════════════════════════════════════════${RESET}"
echo ""