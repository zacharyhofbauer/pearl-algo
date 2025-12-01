# CLI Workflow Consolidation & Console Output Polish Plan

## Executive Summary

This plan outlines the consolidation of CLI workflows and enhancement of console outputs to create a professional, trader-friendly monitoring experience. The goal is to unify multiple entry points into a cohesive command structure while providing clear, actionable, and visually appealing console output for real-time trading operations.

---

## Current State Analysis

### CLI Entry Points Inventory

1. **`scripts/workflow.py`** - Main interactive menu (9 options)
   - Daily signals generation
   - Status dashboard
   - Paper trading loop
   - Data download
   - Gateway management
   - Signal/report viewing

2. **`scripts/automated_trading.py`** - Automated trading agent entry point
   - Long-running trading loop
   - Verbose analysis output
   - Cycle summaries

3. **`scripts/setup_assistant.py`** - Setup & management assistant
   - Gateway management
   - System status checks
   - Connection testing
   - Setup wizard

4. **`scripts/status_dashboard.py`** - Real-time status dashboard
   - Live updating dashboard
   - Gateway, performance, risk panels

5. **`scripts/daily_workflow.py`** - Daily workflow wrapper
   - Runs signals + report generation

6. **`scripts/live_paper_loop.py`** - Paper trading loop
   - Basic print statements
   - Minimal formatting

7. **`scripts/run_daily_signals.py`** - Signal generation
   - Simple print statements

8. **`scripts/daily_report.py`** - Report generation
   - Simple print statements

9. **`scripts/risk_monitor.py`** - Risk monitoring
   - Basic print statements

### Current Issues Identified

1. **Fragmented Entry Points**: Multiple scripts with overlapping functionality
   - `workflow.py` and `setup_assistant.py` both manage Gateway
   - `automated_trading.py` and `live_paper_loop.py` both do paper trading
   - Inconsistent command-line interfaces

2. **Inconsistent Console Output**:
   - Mix of Rich library (workflow.py, status_dashboard.py, automated_trading_agent.py) and plain print (live_paper_loop.py, run_daily_signals.py)
   - Different formatting styles across scripts
   - Some scripts verbose, others minimal
   - No unified color scheme or output structure

3. **Redundant Functionality**:
   - Gateway management in both `workflow.py` and `setup_assistant.py`
   - Status checking scattered across multiple scripts
   - Signal generation and reporting split across multiple scripts

4. **Poor Trader Experience**:
   - No unified command structure
   - Inconsistent information density
   - Missing key metrics in some outputs
   - No clear separation between operational vs. monitoring commands

---

## Proposed Solution

### Phase 1: Unified CLI Command Structure

Create a single entry point: `pearlalgo` (or `python -m pearlalgo.cli`) with subcommands:

```
pearlalgo
├── status          # Quick status check (gateway, performance, risk)
├── dashboard        # Live updating dashboard (enhanced)
├── signals          # Generate daily signals
├── report           # Generate daily report
├── trade            # Trading operations
│   ├── paper        # Start paper trading loop
│   ├── auto         # Start automated trading agent
│   └── monitor      # Monitor risk limits
├── gateway          # Gateway management
│   ├── start
│   ├── stop
│   ├── restart
│   ├── status
│   └── logs
├── data             # Data operations
│   ├── download     # Download historical data
│   └── validate     # Validate data quality
└── setup            # Setup wizard
```

**Benefits**:
- Single entry point for all operations
- Consistent command structure
- Easy to discover functionality
- Can be installed as system command

### Phase 2: Console Output Standardization

#### 2.1 Unified Output Format

Create a `ConsoleOutput` utility class that provides:

1. **Consistent Color Scheme**:
   - ✅ Success: Green
   - ⚠️ Warning: Yellow
   - ❌ Error: Red
   - ℹ️ Info: Cyan
   - 📊 Data: Blue
   - 🔒 Risk: Magenta

2. **Output Levels**:
   - `QUIET`: Minimal output (errors only)
   - `NORMAL`: Standard output (default)
   - `VERBOSE`: Detailed output with analysis
   - `DEBUG`: Full debugging information

3. **Structured Output Types**:
   - **Status Panels**: Gateway, risk, performance
   - **Trade Alerts**: Entry/exit notifications with key metrics
   - **Analysis Tables**: Signal analysis, risk breakdown
   - **Progress Indicators**: Long-running operations
   - **Summary Cards**: Cycle summaries, daily summaries

#### 2.2 Trader-Focused Metrics Display

For real-time monitoring, prioritize:

1. **Critical Metrics** (always visible):
   - Current P&L (realized + unrealized)
   - Risk status (OK/NEAR_LIMIT/HARD_STOP)
   - Open positions count
   - Gateway connection status

2. **Trading Metrics** (per symbol):
   - Current price
   - Signal direction (BUY/SELL/FLAT)
   - Position size
   - Entry price (if position open)
   - Unrealized P&L (if position open)

3. **Risk Metrics**:
   - Daily loss limit remaining
   - Trades today / max trades
   - Cooldown status
   - Drawdown percentage

4. **System Metrics**:
   - Gateway uptime
   - Last successful data fetch
   - Error count
   - Cycle count

#### 2.3 Enhanced Dashboard Layout

Improve `status_dashboard.py` with:

1. **Multi-Panel Layout**:
   ```
   ┌─────────────────────────────────────────┐
   │         Header (timestamp, cycle #)     │
   ├──────────────┬──────────────────────────┤
   │ Gateway      │ Performance              │
   │ Status       │ P&L, Trades, Win Rate    │
   ├──────────────┼──────────────────────────┤
   │ Risk State   │ Latest Signals           │
   │ Status, Limit│ Symbol, Direction, Size  │
   ├──────────────┴──────────────────────────┤
   │         Open Positions                  │
   │ Symbol | Size | Entry | P&L | %        │
   └─────────────────────────────────────────┘
   ```

2. **Real-Time Updates**:
   - Auto-refresh every 5 seconds
   - Highlight changes (new trades, status changes)
   - Blink/flash for critical alerts

3. **Keyboard Shortcuts**:
   - `q` - Quit
   - `r` - Refresh now
   - `s` - Show signals detail
   - `p` - Show positions detail
   - `?` - Show help

### Phase 3: Code Consolidation

#### 3.1 Create Unified CLI Module

**New Structure**:
```
src/pearlalgo/cli/
├── __init__.py
├── main.py              # Main CLI entry point
├── commands/
│   ├── __init__.py
│   ├── status.py        # Status command
│   ├── dashboard.py     # Dashboard command
│   ├── signals.py       # Signals command
│   ├── report.py        # Report command
│   ├── trade.py         # Trading commands
│   ├── gateway.py       # Gateway commands
│   ├── data.py          # Data commands
│   └── setup.py         # Setup command
├── output/
│   ├── __init__.py
│   ├── console.py       # Console output utilities
│   ├── panels.py        # Panel builders
│   ├── tables.py        # Table builders
│   └── colors.py        # Color scheme
└── utils/
    ├── __init__.py
    └── formatting.py    # Formatting utilities
```

#### 3.2 Migrate Existing Scripts

1. **Keep as wrappers** (for backward compatibility):
   - `scripts/workflow.py` → calls `pearlalgo` CLI
   - `scripts/automated_trading.py` → calls `pearlalgo trade auto`
   - `scripts/setup_assistant.py` → calls `pearlalgo setup`

2. **Consolidate logic**:
   - Move Gateway management to `cli/commands/gateway.py`
   - Move status logic to `cli/commands/status.py`
   - Move dashboard logic to `cli/commands/dashboard.py`

#### 3.3 Create Output Utilities

**`cli/output/console.py`**:
```python
class TraderConsole:
    """Unified console output for trading operations."""
    
    def status_panel(self, gateway, risk, performance)
    def trade_alert(self, symbol, side, size, price, reason)
    def analysis_table(self, symbol, signal, risk_state)
    def cycle_summary(self, cycle_num, trades, pnl, positions)
    def error_alert(self, error, context)
    def progress_bar(self, task, current, total)
```

---

## Implementation Plan

### Step 1: Create CLI Infrastructure (Week 1)
- [ ] Create `src/pearlalgo/cli/` structure
- [ ] Implement `cli/output/console.py` with TraderConsole class
- [ ] Implement color scheme and formatting utilities
- [ ] Create basic command structure with Click or argparse

### Step 2: Migrate Core Commands (Week 1-2)
- [ ] Migrate status command
- [ ] Migrate dashboard command (enhance layout)
- [ ] Migrate signals command
- [ ] Migrate report command
- [ ] Migrate gateway commands

### Step 3: Enhance Trading Commands (Week 2)
- [ ] Migrate automated trading agent
- [ ] Enhance output with analysis tables
- [ ] Add cycle summaries
- [ ] Improve error handling and recovery messages

### Step 4: Polish Console Outputs (Week 2-3)
- [ ] Standardize all output formats
- [ ] Add trader-focused metrics
- [ ] Implement keyboard shortcuts for dashboard
- [ ] Add real-time update indicators

### Step 5: Testing & Documentation (Week 3)
- [ ] Test all commands
- [ ] Update README with new CLI structure
- [ ] Create migration guide for existing scripts
- [ ] Add command help text

### Step 6: Backward Compatibility (Week 3)
- [ ] Update existing scripts to call new CLI
- [ ] Ensure all existing workflows still work
- [ ] Deprecation warnings for old scripts

---

## Example Output Improvements

### Before (live_paper_loop.py):
```
[2025-11-26T10:30:00] ES FUT sr: LONG qty=1 risk=SAFE price=4500.25
```

### After (unified CLI):
```
┌─────────────────────────────────────────────────────────┐
│ 🟢 TRADE ALERT: ES                                      │
├─────────────────────────────────────────────────────────┤
│ Direction:  [bold green]LONG[/bold green]                              │
│ Size:       1 contract                                  │
│ Price:      $4,500.25                                   │
│ Risk:       ✅ SAFE ($2,500 buffer remaining)          │
│ Signal:     Support bounce + VWAP above price          │
│ Entry:      $4,500.25 @ 10:30:00 UTC                   │
└─────────────────────────────────────────────────────────┘
```

### Before (automated_trading_agent.py):
```
[Cycle #5] Processing ES...
```

### After (unified CLI):
```
┌─────────────────────────────────────────────────────────┐
│ 📊 Cycle #5 - 2025-11-26 10:30:00 UTC                  │
├─────────────────────────────────────────────────────────┤
│ 🔍 Analyzing ES...                                      │
│ ✅ Data: 288 bars | Latest: $4,500.25                   │
│ 🧠 Signal: LONG (Support bounce detected)               │
│ 💰 Size: 1 contract | Risk: SAFE                        │
│ ✅ Executed: Order ID 12345                             │
│                                                          │
│ Daily P&L: $125.50 (R: $50.00, U: $75.50)              │
│ Trades Today: 3 | Open Positions: 2                    │
└─────────────────────────────────────────────────────────┘
```

---

## Success Criteria

1. ✅ Single entry point (`pearlalgo`) for all operations
2. ✅ Consistent, professional console output across all commands
3. ✅ Trader-focused metrics always visible
4. ✅ Real-time dashboard with keyboard shortcuts
5. ✅ Backward compatibility with existing scripts
6. ✅ Clear error messages and recovery guidance
7. ✅ Comprehensive help system (`pearlalgo --help`)

---

## Questions for Approval

1. **CLI Library**: Use Click, argparse, or Typer? (Recommendation: Click for better UX)
2. **Output Verbosity**: Default to NORMAL or VERBOSE? (Recommendation: NORMAL)
3. **Dashboard Refresh**: Default refresh rate? (Recommendation: 5 seconds)
4. **Backward Compatibility**: How long to maintain old scripts? (Recommendation: 1 version cycle)
5. **Color Support**: Auto-detect terminal color support? (Recommendation: Yes, with fallback)

---

## Next Steps

Once approved, I will:
1. Create the CLI infrastructure
2. Implement core commands with polished output
3. Migrate existing functionality
4. Test thoroughly
5. Update documentation

Please review and approve this plan, or suggest modifications before we begin implementation.

