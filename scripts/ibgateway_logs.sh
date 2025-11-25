#!/usr/bin/env bash
set -euo pipefail

LOG_STDOUT="${HOME}/ibgateway.out.log"
LOG_STDERR="${HOME}/ibgateway.err.log"

echo "==> Tailing ibgateway.out.log (Ctrl+C to stop)"
tail -f "${LOG_STDOUT}" &
PID1=$!

echo "==> Tailing ibgateway.err.log (Ctrl+C to stop)"
tail -f "${LOG_STDERR}" &
PID2=$!

trap "kill ${PID1} ${PID2}" INT TERM
wait
