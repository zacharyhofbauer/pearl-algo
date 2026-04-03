#!/bin/sh
# Autostart: open 2-3 terminals with live logs (agent, API) and transparency.
# Run by session via ~/.config/autostart/pearlalgo-dashboard.desktop

sleep 5

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LAUNCHER="${PROJECT_ROOT}/scripts/monitoring/start-live-logs-terminals.sh"
export PATH="/usr/bin:/bin:${PATH}"

if [ -x "${LAUNCHER}" ]; then
    "${LAUNCHER}"
fi
