#!/bin/bash
# PearlAlgo Nightly Backtest Runner
# Designed for cron: collects data, runs backtest, produces analysis.
#
# Cron example (run at 5:30 PM ET daily, before session open):
#   30 17 * * * /home/pearlalgo/projects/pearl-algo/scripts/backtesting/run_nightly_backtest.sh
#
# Output files:
#   data/backtest/latest_results.json   - Full backtest results + trades
#   data/backtest/latest_analysis.json  - Session-aware analysis

set -euo pipefail

WORKSPACE="${HOME}/projects/pearl-algo"
cd "${WORKSPACE}"

# Activate virtualenv
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
elif [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

DAYS=${1:-14}
RESULTS_DIR="data/backtest"
RESULTS_FILE="${RESULTS_DIR}/latest_results.json"
ANALYSIS_FILE="${RESULTS_DIR}/latest_analysis.json"

mkdir -p "${RESULTS_DIR}"

echo "========================================"
echo "  PearlAlgo Nightly Backtest"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "  Days: ${DAYS}"
echo "========================================"

# Step 1: Refresh data (from cache files; IBKR may not be connected)
echo ""
echo "[1/3] Refreshing data..."
python scripts/backtesting/data_collector.py --days "${DAYS}" --from-cache 2>&1 || {
    echo "WARNING: Data collection had errors, proceeding with available data"
}

# Step 2: Run backtest with current live config + all filters
echo ""
echo "[2/3] Running backtest..."
python scripts/backtesting/backtest_engine.py \
    --days "${DAYS}" \
    --trailing \
    --json-out "${RESULTS_FILE}" 2>&1

# Step 3: Run analysis
echo ""
echo "[3/3] Analyzing results..."
if [ -f "${RESULTS_FILE}" ]; then
    python scripts/backtesting/analyze_backtest.py \
        "${RESULTS_FILE}" \
        --json-out "${ANALYSIS_FILE}" 2>&1
else
    echo "WARNING: No results file found, skipping analysis"
fi

echo ""
echo "========================================"
echo "  Nightly backtest complete"
echo "  Results: ${RESULTS_FILE}"
echo "  Analysis: ${ANALYSIS_FILE}"
echo "========================================"
