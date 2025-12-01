# ⚡ Quick Start Guide

## Start Trading
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

## Micro Contracts (Fast Pace)
```bash
bash scripts/run_micro_strategy.sh
# Trades: MGC, MYM, MCL, MNQ, MES (1min intervals, 3-5 contracts)
```

## Diagnostics
```bash
python scripts/debug_trading.py      # Check configuration
python scripts/health_check.py     # System health
python scripts/status_dashboard.py  # Real-time dashboard
```

## Configuration
- `.env`: `PEARLALGO_PROFILE=live` and `PEARLALGO_ALLOW_LIVE_TRADING=true`
- See `docs/AUTOMATED_TRADING.md` for full setup guide
