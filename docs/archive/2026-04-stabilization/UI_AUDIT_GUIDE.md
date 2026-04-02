# UI Audit Guide

> How to use the audit tools in the web dashboard and Telegram.

---

## 1. Web Dashboard — Audit Panel

Access the Audit Panel by clicking the **"Audit"** tab in the main dashboard navigation.

- IBKR Virtual: `https://pearlalgo.io` → Audit tab
- Tradovate Paper: `https://pearlalgo.io/?account=tv_paper` → Audit tab

The Audit Panel has five sub-tabs:

---

### Trade Ledger

A filterable, sortable table of all trades (entries and exits).

**Columns:**

| Column | Description |
|--------|-------------|
| Time | Trade timestamp (local timezone) |
| Account | IBKR Virtual or Tradovate Paper |
| Direction | LONG or SHORT |
| Entry Price | Fill price at entry |
| Exit Price | Fill price at exit (blank if position is open) |
| Quantity | Number of contracts |
| P&L | Realized profit/loss (commission-adjusted) |
| Exit Reason | stop, target, or manual |
| Duration | Time held (entry to exit) |

**Filters:**
- Account selector (all, IBKR Virtual, Tradovate Paper)
- Date range picker
- Direction (all, LONG, SHORT)
- Outcome (all, winners, losers)

**Export:** Click the **Export CSV** button to download the filtered trade data.

---

### Signal Decisions

Shows every signal the strategy generated and whether it was executed or rejected.

**Layout:**
- Top summary: total generated vs total rejected (with percentages)
- Table with columns:

| Column | Description |
|--------|-------------|
| Time | Signal timestamp |
| Account | Target account |
| Direction | LONG or SHORT |
| Confidence | Strategy confidence score (0–1) |
| Status | `executed` or `rejected` |
| Rejection Reason | Why the signal was rejected (blank if executed) |

**Common rejection reasons:**
- `circuit_breaker_daily_loss` — Daily loss limit reached
- `circuit_breaker_consecutive` — Too many consecutive losses
- `market_closed` — Signal arrived outside trading hours
- `duplicate_signal` — Same direction + bar already processed
- `low_confidence` — Confidence below threshold

---

### System Events

A chronological timeline of system events with color-coded severity.

**Color coding:**

| Color | Event Types |
|-------|-------------|
| Green | Agent starts, successful reconnections |
| Yellow | Connection drops (recovered), config reloads |
| Red | Circuit breaker trips, agent crashes, error threshold breaches |
| Gray | Agent clean stops, routine events |

**Each event card shows:**
- Timestamp
- Event type (with icon)
- Account
- Key details from the event payload

**Filters:**
- Account selector
- Severity (all, info, warning, error)
- Date range

---

### Equity History

Daily balance snapshots plotted as a line chart for each account.

**Features:**
- Dual-axis chart: one line per account
- Hover tooltips showing exact balance, equity, and unrealized P&L
- Date range selector (7d, 30d, 90d, all)
- Table view toggle showing raw daily values

**Data source:** `equity_snapshot` events from the audit database.

---

### Reconciliation

Side-by-side comparison of agent-tracked P&L vs broker-reported P&L.

**Layout:**
- One card per account
- Each card shows:

| Field | Description |
|-------|-------------|
| Period | Date range of the reconciliation |
| Agent P&L | P&L calculated by PearlAlgo |
| Broker P&L | P&L reported by the broker (IBKR or Tradovate) |
| Difference | Absolute difference |
| Status | Match (green) or Mismatch (red) |

**Mismatch threshold:** Differences under $2.00 are considered a match (accounts for rounding and commission estimation).

---

## 2. Telegram — Audit Commands

All audit commands are available through the PearlAlgo Telegram bot.

### Interactive Menu

Send `/audit` (with no arguments) to open an inline keyboard with all audit options:

```
/audit
```

The bot responds with buttons for each audit command — tap to execute.

### Commands

#### `/audit trades [7d|30d]`

Trade summary for the specified period.

```
📊 Trade Summary (7d)

IBKR Virtual:
  Trades: 12 | Win Rate: 66.7%
  P&L: +$187.50

Tradovate Paper:
  Trades: 12 | Win Rate: 66.7%
  P&L: +$185.00

Top trade: LONG @ 21,450.25 → 21,478.00 (+$27.75)
Worst trade: SHORT @ 21,500.00 → 21,518.50 (-$18.50)
```

#### `/audit signals [7d|30d]`

Signal generation and rejection breakdown.

```
📡 Signal Decisions (7d)

Generated: 45 | Executed: 12 | Rejected: 33
Execution Rate: 26.7%

Top Rejection Reasons:
  1. low_confidence — 18 (54.5%)
  2. circuit_breaker_daily_loss — 8 (24.2%)
  3. market_closed — 5 (15.2%)
  4. duplicate_signal — 2 (6.1%)
```

#### `/audit health [7d|30d]`

System health report.

```
🏥 System Health (7d)

Uptime: 99.2%
Restarts: 2 (1 clean, 1 crash)
Connection Drops: 3 (avg 8s, all recovered)
Circuit Breaker Trips: 1
Error Threshold Breaches: 0
```

#### `/audit reconcile`

Latest reconciliation results.

```
🔍 Reconciliation

IBKR Virtual:
  Agent: +$187.50 | Broker: N/A (virtual)
  Status: ✅ Virtual only

Tradovate Paper:
  Agent: +$185.00 | Broker: +$183.50
  Difference: $1.50
  Status: ✅ Match
```

#### `/audit export`

Sends a CSV file with the last 30 days of audit data as a Telegram document.

---

## 3. Common Scenarios

### Investigating a Bad Trade

**Goal:** Understand why a trade was taken and what went wrong.

1. **Signal Decisions tab** — Find the signal that triggered the trade.
   - Check the confidence score. Was it borderline?
   - Look at the indicators in the signal payload for context.
2. **Trade Ledger tab** — Find the corresponding trade entry and exit.
   - Check the exit reason: was it stopped out, or did it hit target?
   - Look at the duration — was it unusually fast (slippage) or slow (ranging market)?
3. **Telegram shortcut:**
   ```
   /audit signals 7d    # Find the signal
   /audit trades 7d     # Find the trade
   ```

### Checking System Reliability

**Goal:** Verify the system is running stably and not missing signals.

1. **System Events tab** — Look for patterns:
   - Frequent restarts? Check for crashes (red events).
   - Connection drops? Check duration and whether they recovered.
   - Circuit breaker trips? Check which rule triggered.
2. **Signal Decisions tab** — Look for rejected signals with reason `connection_drop` or `error_threshold`.
3. **Telegram shortcut:**
   ```
   /audit health 7d     # Quick health summary
   ```

### Verifying Broker P&L

**Goal:** Ensure agent-tracked P&L matches what the broker reports.

1. **Reconciliation tab** — Check the latest reconciliation for each account.
   - Green "Match" = difference < $2.00. Normal.
   - Red "Mismatch" = investigate further.
2. **If mismatched:**
   - Check **Trade Ledger** for trades with unusual P&L.
   - Compare fill prices in the audit log vs Tradovate's fill history.
   - Common cause: commission estimation drift (auto-corrected on next sync).
3. **Telegram shortcut:**
   ```
   /audit reconcile     # Quick reconciliation check
   ```

### Reviewing Daily Performance

**Goal:** End-of-day review of trading activity.

1. **Equity History tab** — Check today's balance change vs yesterday.
2. **Trade Ledger tab** — Filter to today, review all trades.
3. **Signal Decisions tab** — Filter to today, check how many signals were generated vs executed.
4. **Telegram shortcut:**
   ```
   /audit trades 7d     # Recent trade summary
   /audit signals 7d    # Recent signal summary
   ```
