# Final Project Review - Additional Cleanup

## Files to Remove

### Root Level Files
1. ✅ `test_ibkr_connection.py` - Duplicate of `scripts/smoke_test_ibkr.py`
2. ✅ `test_signal_improvements.sh` - References removed tests (test_exit_signals.py, etc.)
3. ✅ `run_service.sh` - References removed `continuous_service`
4. ✅ `setup_and_test.sh` - References removed tests
5. ✅ `TROUBLESHOOTING.md` - References removed components (options, continuous_service)
6. ⚠️ `docker-compose.yml` - References LangGraph, simplify or remove if not using Docker

### Config Files
1. ✅ `config/config.production.yaml` - References options trading and removed continuous_service

### Directories to Remove
1. ✅ `scripts/legacy/` - All legacy scripts
2. ✅ `docs/legacy/` - All legacy documentation (40+ files)
3. ✅ `src/pearlalgo/data/` - Not used by NQ agent
4. ✅ `src/pearlalgo/futures/` - Disabled, says it's for options (we're doing NQ futures, but this module is disabled)
5. ⚠️ `src/pearlalgo/models/` - Check if used (empty __init__.py)
6. ⚠️ `reports/` - Old reports, can remove

### Utils to Review
1. ⚠️ `src/pearlalgo/utils/discord_alerts.py` - Remove if not using Discord
2. ⚠️ `src/pearlalgo/utils/brain_log.py` - Check if used
3. ⚠️ `src/pearlalgo/utils/journal.py` - Check if used
4. ⚠️ `src/pearlalgo/utils/startup_validation.py` - Check if used
5. ⚠️ `src/pearlalgo/utils/suppress_warnings.py` - Check if used

### Tests to Review
1. ✅ `tests/test_worker_pool.py` - References removed worker pool
2. ⚠️ `tests/test_margin_models.py` - Check if margin models are used
3. ⚠️ `tests/test_risk_calculators.py` - Check if needed
4. ⚠️ `tests/test_telegram_exits.py` - Check if relevant
5. ⚠️ `tests/test_trade_ledger.py` - Check if trade ledger is used
6. ⚠️ `tests/test_market_data_provider.py` - Check if market_data_provider is used

### Backtesting
1. ⚠️ `src/pearlalgo/backtesting/` - Keep if you want backtesting, remove if not

### Monitoring
1. ⚠️ `src/pearlalgo/monitoring/health.py` - Keep for health checks, but check if it's used
