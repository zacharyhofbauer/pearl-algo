#!/usr/bin/env bash
# Check Tradovate positions via REST API
# Usage: bash check-positions.sh [--orders] [--account] [--fills N] [--all] [--json]
set -a
source /home/pearlalgo/.config/pearlalgo/secrets.env
source /home/pearlalgo/PearlAlgoWorkspace/.env
set +a
cd /home/pearlalgo/PearlAlgoWorkspace
PYTHONPATH=/home/pearlalgo/PearlAlgoWorkspace .venv/bin/python3 scripts/check_tradovate.py "$@"
