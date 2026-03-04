#!/bin/sh
# Run live colorized logs for one systemd unit. Called by start-live-logs-terminals.sh.
# Usage: run-journalctl-colored.sh <unit-name>
# Example: run-journalctl-colored.sh pearlalgo-agent

UNIT="${1:-pearlalgo-agent}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COLORIZER="${SCRIPT_DIR}/colorize-logs.awk"

if ! systemctl list-unit-files --type=service "$UNIT" 2>/dev/null | grep -q "^${UNIT}"; then
  echo "Unit '${UNIT}' not found or not a service."
  echo "Check: systemctl list-units --type=service | grep pearlalgo"
  exec sh
fi

journalctl -u "$UNIT" -f -o cat -q -n 200 2>/dev/null | awk -f "${COLORIZER}" 2>/dev/null || journalctl -u "$UNIT" -f -o cat -q -n 200
exec sh
