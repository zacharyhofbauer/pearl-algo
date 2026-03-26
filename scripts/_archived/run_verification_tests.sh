#!/bin/bash
# Run all verification checks for MNQ + Tradovate (IBKR data only) setup.
# Usage: ./scripts/run_verification_tests.sh

set -e
cd "$(dirname "$0")/.."

echo "=== 1. Tradovate execution config ==="
.venv/bin/python scripts/verify_tradovate_execution.py
echo ""

echo "=== 2. MNQ + Tradovate setup (config + optional Gateway check) ==="
.venv/bin/python scripts/verify_mnq_tradovate_setup.py
echo ""

echo "=== 3. Gateway API (optional; skip if Gateway not running) ==="
if ./scripts/gateway/gateway.sh api-ready 2>/dev/null; then
  echo "   Gateway is ready for data connections."
else
  echo "   Gateway not ready or not running. Start with: ./pearl.sh gateway start"
  echo "   Then run: ./scripts/gateway/gateway.sh reduce-login-prompts"
fi
echo ""

echo "=== Verification complete ==="
echo "Start the agent: ./pearl.sh start   or   ./scripts/lifecycle/tv_paper_eval.sh start --background"
echo "Watch for signals: tail -f logs/agent_TV_PAPER.log | grep -E 'signal|place_oso|Order placed'"
