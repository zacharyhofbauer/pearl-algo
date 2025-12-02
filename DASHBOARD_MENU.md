# 📊 Interactive Dashboard Menu Guide

## Quick Start

### Interactive Mode (Recommended)
```bash
pearlalgo dashboard --interactive
# or
python scripts/dashboard.py --interactive
```

This opens an interactive dashboard with a menu panel showing all available commands.

### Live Dashboard with Menu
```bash
pearlalgo dashboard --menu
# Shows live updating dashboard with menu panel visible
```

## Menu Options

When in interactive mode, you'll see a menu with these options:

### Trading Commands
- **1** - Generate Signals (ES, NQ, GC with SR strategy)
- **2** - Start Micro Trading (MGC, MYM, MCL, MNQ, MES)
- **3** - Start Standard Trading (ES, NQ, GC)
- **4** - Stop All Trading (Kills all trading processes)

### Analysis & Monitoring
- **5** - Performance Analysis (Shows summary of trading performance)
- **6** - Test Broker Connection (Tests IBKR connection)
- **C** - View Trading Logs (Shows last 30 lines of micro_trading.log)

### Gateway Management
- **7** - Gateway Status (Check if IB Gateway is running)
- **8** - Gateway Start (Start IB Gateway and wait)
- **9** - Gateway Restart (Restart IB Gateway)

### File Management
- **A** - View Latest Signals (List latest signal CSV files)
- **B** - View Latest Reports (List latest report markdown files)

### System & Testing
- **D** - System Health Check (Run comprehensive health check)
- **E** - Walk-Forward Test Help (Show walk-forward testing options)
- **F** - Backtest Validation Help (Show backtest validation options)

### Exit
- **Q** - Quit Dashboard

## Usage Tips

1. **Interactive Mode**: Best for daily use - shows dashboard and lets you execute commands without leaving
2. **Menu Panel**: Always visible in interactive mode, shows all available commands
3. **Command Execution**: Commands run in the foreground, you'll see output and can press Enter to return
4. **Quick Access**: No need to remember command syntax - just press the number/letter

## Example Workflow

```bash
# Start interactive dashboard
pearlalgo dashboard --interactive

# Daily routine:
# 1. Check gateway status (press 7)
# 2. If not running, start gateway (press 8)
# 3. Generate signals (press 1)
# 4. Start trading (press 2 for micro or 3 for standard)
# 5. Monitor performance (press 5)
# 6. When done, stop trading (press 4)
# 7. Quit (press Q)
```

## Keyboard Shortcuts

- **Ctrl+C** - Exit dashboard immediately
- **Enter** - After command execution, return to dashboard
- **Q** - Quit gracefully

## Notes

- All commands execute from the project root directory
- Commands that require confirmation will prompt you
- Some commands (like starting trading) may take time to complete
- The dashboard refreshes automatically in live mode



