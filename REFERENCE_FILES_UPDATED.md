# Reference Files Updated

**Date**: After cleanup completion  
**Purpose**: Update all reference files with new changes

---

## Files Updated

### ✅ CHEAT_SHEET_SHORT.md
**Updates**:
- Replaced archived script references with new commands
- Added `debug_env.py` and `debug_ibkr.py` commands
- Updated dashboard command to `scripts/dashboard.py` (unified)
- Updated trading commands to LangGraph trader
- Added environment variables section with `dummy_mode` flag
- Updated troubleshooting with new debug scripts
- Removed references to archived scripts:
  - `scripts/start_micro.sh` → `./start_micro_paper_trading.sh`
  - `scripts/status_dashboard.py` → `scripts/dashboard.py`
  - `scripts/kill_my_processes.sh` → `Ctrl+C` or `pkill`
  - `scripts/test_broker_connection.py` → `scripts/debug_ibkr.py`

### ✅ CHEAT_SHEET.md
**Updates**:
- Updated all script references to current scripts
- Added debug scripts (`debug_env.py`, `debug_ibkr.py`)
- Updated dashboard commands to unified dashboard
- Updated trading commands to LangGraph trader
- Updated troubleshooting sections
- Updated quick reference table with new commands
- Removed references to archived scripts

---

## Key Changes Reflected

### New Debug Scripts
- `python scripts/debug_env.py` - Verify .env configuration
- `python scripts/debug_ibkr.py` - Test IBKR connection

### Updated Scripts
- `scripts/dashboard.py` - Unified dashboard (replaces status_dashboard.py)
- `scripts/health_check.py` - Health check
- `scripts/system_health_check.py` - System health

### New Environment Variables
- `PEARLALGO_DUMMY_MODE` - Explicit dummy data mode flag
- Updated IBKR configuration variables

### Updated Trading Commands
- `./start_micro_paper_trading.sh` - Quick start script
- `python -m pearlalgo.live.langgraph_trader` - Main trading system
- `python scripts/daily_workflow.py` - Daily workflow

### Updated Monitoring
- `./monitor_trades.sh` - Monitor script
- `tail -f logs/langgraph_trading.log` - Main trading logs

---

## Testing Checklist

Use these commands to verify everything works:

```bash
# 1. Verify configuration
python scripts/debug_env.py

# 2. Test IBKR connection (if using IBKR)
python scripts/debug_ibkr.py

# 3. View dashboard
python scripts/dashboard.py

# 4. Health check
python scripts/health_check.py

# 5. Start paper trading
./start_micro_paper_trading.sh

# 6. Monitor logs
tail -f logs/langgraph_trading.log
```

---

## Notes

- All archived script references have been removed or replaced
- All new features (dummy_mode, debug scripts) are documented
- All commands point to current, active scripts
- Reference files are now aligned with the cleaned-up repository

---

**All reference files are now up-to-date and ready for testing!**

