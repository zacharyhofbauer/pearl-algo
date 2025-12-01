# ⚡ Quick Reference Card

## 🚀 Start Trading
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/automated_trading.py --symbols ES NQ --strategy sr --interval 300
```

## 🔍 Diagnostics
```bash
python scripts/debug_trading.py      # Check configuration
python scripts/health_check.py     # System health
python scripts/status_dashboard.py  # Real-time dashboard
```

## ⚙️ Configuration
- `.env` file: `PEARLALGO_PROFILE=live` and `PEARLALGO_ALLOW_LIVE_TRADING=true`
- Risk profile: `config/prop_profile.yaml` or `config/micro_strategy_config.yaml`

## 📊 Common Commands
| Task | Command |
|------|---------|
| Regular trading | `python scripts/automated_trading.py --symbols ES NQ --strategy sr` |
| Micro contracts | `bash scripts/run_micro_strategy.sh` |
| All strategies | `bash scripts/run_all_strategies.sh` |
| Check IB Gateway | `sudo systemctl status ibgateway.service` |

## 🐛 Troubleshooting
1. No trades? → Run `python scripts/debug_trading.py`
2. "DRY RUN MODE"? → Check `.env` file
3. "FLAT signal"? → Normal, no opportunities
4. Connection error? → Start IB Gateway

## 📚 Full Docs
- Complete guide: `docs/AUTOMATED_TRADING.md`
- Summary: `PROJECT_SUMMARY.md`
- Config: `ENV_CONFIGURATION.md`
