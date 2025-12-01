#!/bin/bash
# Fast-paced micro contracts trading strategy
# Runs micro futures (MGC, MYM, MRTY, MCL) with faster intervals and 3-5 contracts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"
source .venv/bin/activate

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  🚀 Micro Contracts Fast-Paced Strategy                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "Symbols: MGC (Micro Gold), MYM (Micro Dow), MRTY (Micro Russell), MCL (Micro Crude)"
echo "Strategy: sr (Support/Resistance)"
echo "Interval: 60s (1 minute - fast paced)"
echo "Contract Size: 3-5 micro contracts"
echo ""

python scripts/automated_trading.py \
  --symbols MGC MYM MRTY MCL \
  --sec-types FUT FUT FUT FUT \
  --strategy sr \
  --interval 60 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 10 \
  --log-file logs/micro_trading.log

