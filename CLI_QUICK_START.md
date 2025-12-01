# PearlAlgo CLI Quick Start Guide

## Installation

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e .
```

After installation, the `pearlalgo` command is available system-wide.

## Basic Usage

### System Status
```bash
# Quick status check
pearlalgo status

# Live updating dashboard
pearlalgo dashboard

# Dashboard with custom refresh rate
pearlalgo dashboard --refresh 10
```

### Trading Operations
```bash
# Generate daily signals
pearlalgo signals --strategy sr --symbols ES NQ GC

# Start paper trading
pearlalgo trade paper --symbols ES NQ --strategy sr --interval 300

# Start automated trading agent
pearlalgo trade auto --symbols ES NQ --strategy sr --interval 300

# Monitor risk limits
pearlalgo trade monitor --max-daily-loss 2500 --interval 60
```

### Gateway Management
```bash
# Start Gateway (and wait for it to be ready)
pearlalgo gateway start --wait

# Check Gateway status
pearlalgo gateway status

# View Gateway logs
pearlalgo gateway logs --lines 50

# Stop Gateway
pearlalgo gateway stop

# Restart Gateway
pearlalgo gateway restart --wait
```

### Reports & Data
```bash
# Generate daily report
pearlalgo report

# Generate report for specific date
pearlalgo report --date 20251126

# Download historical data
pearlalgo data download
```

### Setup
```bash
# Run interactive setup wizard
pearlalgo setup
```

## Verbosity Levels

Control output detail with `--verbosity`:

```bash
# Quiet (errors only)
pearlalgo --verbosity QUIET status

# Normal (default)
pearlalgo --verbosity NORMAL status

# Verbose (detailed)
pearlalgo --verbosity VERBOSE trade auto

# Debug (full debugging)
pearlalgo --verbosity DEBUG trade auto
```

## Command Reference

### Main Commands
- `pearlalgo status` - Quick system status
- `pearlalgo dashboard` - Live updating dashboard
- `pearlalgo signals` - Generate trading signals
- `pearlalgo report` - Generate daily report
- `pearlalgo setup` - Setup wizard

### Trading Commands (`pearlalgo trade`)
- `paper` - Paper trading loop
- `auto` - Automated trading agent
- `monitor` - Risk monitoring

### Gateway Commands (`pearlalgo gateway`)
- `start` - Start IB Gateway
- `stop` - Stop IB Gateway
- `restart` - Restart IB Gateway
- `status` - Show Gateway status
- `logs` - View Gateway logs

### Data Commands (`pearlalgo data`)
- `download` - Download historical data
- `validate` - Validate data (placeholder)

## Examples

### Complete Trading Session

```bash
# 1. Check system status
pearlalgo status

# 2. Ensure Gateway is running
pearlalgo gateway start --wait

# 3. Generate signals
pearlalgo signals --strategy sr --symbols ES NQ GC

# 4. Review signals in dashboard
pearlalgo dashboard

# 5. Start automated trading
pearlalgo trade auto --symbols ES NQ --strategy sr --interval 300

# 6. In another terminal, monitor risk
pearlalgo trade monitor --max-daily-loss 2500

# 7. Generate end-of-day report
pearlalgo report
```

### Quick Status Check

```bash
# One-liner to check everything
pearlalgo status && pearlalgo gateway status
```

## Help

Get help for any command:

```bash
# Main help
pearlalgo --help

# Command help
pearlalgo trade --help
pearlalgo gateway --help

# Subcommand help
pearlalgo trade auto --help
pearlalgo gateway start --help
```

## Migration from Old Scripts

Old scripts still work, but you can migrate to the new CLI:

| Old Command | New Command |
|------------|-------------|
| `python scripts/workflow.py --signals` | `pearlalgo signals` |
| `python scripts/status_dashboard.py` | `pearlalgo dashboard` |
| `python scripts/automated_trading.py` | `pearlalgo trade auto` |
| `python scripts/live_paper_loop.py` | `pearlalgo trade paper` |
| `python scripts/setup_assistant.py` | `pearlalgo setup` |

## Tips

1. **Use `--wait` with gateway commands** to automatically wait for Gateway to be ready
2. **Use `--verbosity VERBOSE`** when debugging trading decisions
3. **Run `pearlalgo status`** regularly to monitor system health
4. **Use `pearlalgo dashboard`** for real-time monitoring during trading
5. **Check `pearlalgo gateway logs`** if you encounter connection issues

