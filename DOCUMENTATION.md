# Documentation Index

This is your main documentation hub. All essential documentation has been consolidated here.

## Essential Documentation

### Getting Started
- **[README.md](README.md)** - Main project overview and architecture
- **[START_HERE.md](START_HERE.md)** - Quick start guide for testing and running
- **[TEST_AND_RUN_GUIDE.md](TEST_AND_RUN_GUIDE.md)** - Comprehensive testing and running instructions

### Operations
- **[HOW_TO_USE_24_7_SYSTEM.md](HOW_TO_USE_24_7_SYSTEM.md)** - Complete guide for 24/7 continuous service
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture overview

### Reference Documentation (in `docs/`)
- **[docs/24_7_OPERATIONS_GUIDE.md](docs/24_7_OPERATIONS_GUIDE.md)** - Detailed operations guide
- **[docs/OPTIONS_SCANNING_GUIDE.md](docs/OPTIONS_SCANNING_GUIDE.md)** - Options scanning configuration
- **[docs/STRUCTURE.md](docs/STRUCTURE.md)** - Project structure and organization

## Quick Reference

### Start the Service
```bash
source .venv/bin/activate
python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml
```

### Run Tests
```bash
python3 quick_test.py  # Quick verification
pytest tests/ -v       # Full test suite
```

### Check Health
```bash
curl http://localhost:8080/healthz | jq
```

### View Logs
```bash
tail -f logs/continuous_service.log
```

## Scripts

### Testing
- `quick_test.py` - Quick system verification
- `setup_and_test.sh` - Automated setup and testing
- `test_signal_improvements.sh` - Test signal improvements

### Service Management
- `run_service.sh` - Start the continuous service
