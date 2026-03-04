#!/bin/bash
# =============================================================================
# PearlAlgo CLI monitoring dashboard
#
# One-shot:  ./scripts/monitoring/dashboard.sh
# Live (refresh every 30s):  watch -n 30 -c ./scripts/monitoring/dashboard.sh
# Or:  while true; do clear; ./scripts/monitoring/dashboard.sh; sleep 30; done
#
# Requires: project .venv, systemctl (for service status)
# =============================================================================
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
MARKET="${PEARLALGO_MARKET:-NQ}"

# Services to show (skip if unit doesn't exist)
SERVICES=(
    ibkr-gateway.service
    pearlalgo-agent.service
    pearlalgo-api.service
    pearlalgo-webapp.service
    pearlalgo-telegram.service
    pearlalgo-monitor.service
)

echo "=============================================="
echo "  PearlAlgo CLI Dashboard — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  Market: $MARKET"
echo "=============================================="
echo ""

# --- Systemd service status ---
echo "--- systemd services ---"
for u in "${SERVICES[@]}"; do
    if systemctl list-unit-files --type=service "$u" 2>/dev/null | grep -q "^$u"; then
        s=$(systemctl is-active "$u" 2>/dev/null) || s="?"
        s=${s//$'\n'/}  # trim newlines
        if [[ "$s" == "active" ]]; then
            echo "  ✅ $u"
        else
            echo "  ❌ $u ($s)"
        fi
    fi
done
echo ""

# --- Health monitor (existing script) ---
echo "--- health monitor ---"
if [[ -x "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" scripts/monitoring/monitor.py --market "$MARKET" -v 2>/dev/null || true
else
    echo "  (venv not found at $VENV_PYTHON)"
fi
echo ""

# --- Optional: doctor rollup one-liner (last 24h) ---
echo "--- doctor (last 24h) ---"
if [[ -x "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" scripts/monitoring/doctor_cli.py --hours 24 2>/dev/null | head -25 || echo "  (doctor skipped: config or DB not ready)"
else
    echo "  (venv not found)"
fi

echo ""
echo "=============================================="
echo "  Refresh: watch -n 30 -c $0"
echo "=============================================="
