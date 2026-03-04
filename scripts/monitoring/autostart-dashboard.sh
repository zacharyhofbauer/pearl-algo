#!/bin/sh
# Autostart: open 2–3 terminals with live logs (agent, API, telegram) and transparency.
# Run by session via ~/.config/autostart/pearlalgo-dashboard.desktop

sleep 5

PROJECT_ROOT="/home/pearlalgo/PearlAlgoWorkspace"
LAUNCHER="${PROJECT_ROOT}/scripts/monitoring/start-live-logs-terminals.sh"
export PATH="/usr/bin:/bin:${PATH}"

if [ -x "${LAUNCHER}" ]; then
    "${LAUNCHER}"
fi
