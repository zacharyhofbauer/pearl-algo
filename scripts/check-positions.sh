#!/usr/bin/env bash
# Check Tradovate positions with REAL-TIME unrealized P&L via WebSocket + REST API
# Usage: bash check-positions-v2.sh [--json]
set -a
source /home/pearlalgo/.config/pearlalgo/secrets.env
source /home/pearlalgo/PearlAlgoWorkspace/.env
set +a
cd /home/pearlalgo/PearlAlgoWorkspace
PYTHONPATH=/home/pearlalgo/PearlAlgoWorkspace .venv/bin/python3 scripts/check_positions_realtime.py "$@"
