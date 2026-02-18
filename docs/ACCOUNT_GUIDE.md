# Account Types & Architecture

> How PearlAlgo manages accounts and data sources. **Tradovate Paper is the sole live trading agent.** IBKR Virtual has been archived after validating the strategy.

---

## 1. Account Types

| | IBKR Virtual (Archived) | Tradovate Paper (Live) |
|---|---|---|
| **Status** | Archived — no longer running | **Active — sole live agent** |
| **Purpose** | Inception test account; validated the strategy | Paper trading on Tradovate demo |
| **Broker orders** | None — all P&L was simulated | **Real bracket orders on Tradovate** |
| **Archive / State** | `data/archive/ibkr_virtual/` | `data/tradovate/paper/` |
| **Historical stats** | 1,573 trades · $23,248 P&L · 15 trading days | — |
| **API port** | — | 8001 |
| **Telegram label** | — | `TV-PAPER` |
| **Dashboard URL** | — | `https://pearlalgo.io/?account=tv_paper` |

### IBKR Virtual (Archived)

The original inception test account that validated the PearlAlgo strategy. IBKR Virtual connected to Interactive Brokers Gateway, ran the full strategy (`strategy.analyze()`), and tracked virtual P&L with no broker orders.

- **Final stats:** 1,573 trades, $23,248 P&L over 15 trading days.
- The agent is no longer running. All historical data is archived at `data/archive/ibkr_virtual/`.
- The aggressive strategy settings that generated this performance have been restored to the live Tradovate Paper config (see below).

### Tradovate Paper (Live)

- **The sole live agent.** Runs `pearl_bot_auto` / `strategy.analyze()` on IBKR market data (client IDs 50/51).
- **Trades go directly to Tradovate** — places real bracket orders (entry + stop loss + take profit) on the Tradovate demo account.
- All dashboard numbers come from Tradovate fills and equity. Used for prop firm evaluation (e.g. 50K Rapid).
- **Restored aggressive strategy settings** matching the IBKR Virtual $23K+ run:
  - Faster EMAs: **5/13** (instead of 9/21)
  - Lower confidence threshold: **0.40** (instead of 0.55)
  - All 5 entry trigger types enabled: `ema_cross`, `vwap_cross`, `vwap_retest`, `trend_momentum`, `trend_breakout`

---

## 2. Data Source Architecture

```
┌──────────────────────────────────────────────────┐
│             IBKR Gateway (port 4001)             │
│      Real-time streaming data for live agent     │
└───────────────────────┬──────────────────────────┘
                        │
                ┌───────▼───────┐
                │Tradovate Paper│
                │  (client 50)  │
                │               │
                │  strategy +   │
                │  direct       │
                │  Tradovate    │
                │  orders       │
                └───────┬───────┘
                        │
                ┌───────▼───────┐
                │   Tradovate   │
                │  (execution   │
                │   only)       │
                └───────────────┘
```

> **Note:** IBKR Virtual historical data is archived at `data/archive/ibkr_virtual/`. No IBKR Virtual agent is running.

**Key point:** IBKR provides market data. **Tradovate Paper runs its own strategy and sends orders directly to Tradovate.**

### Why IBKR Stays as Data Source

1. **Faster real-time streaming** — IBKR's TWS/Gateway pushes tick-level data with lower latency than Tradovate's WebSocket feed.
2. **Deeper historical data** — Strategy indicators need multi-day bar history that IBKR serves natively.
3. **Strategy consistency** — The strategy was developed and tuned on IBKR data. Switching data sources would invalidate all parameter tuning.

---

## 3. Execution Path (Tradovate Only)

**No signal forwarding.** Tradovate Paper is the only running agent.

- **Tradovate Paper:** Strategy runs on IBKR data (client 50/51); when a signal is generated it goes **directly** to Tradovate via `follower_execute` → `place_bracket()`.

```
Tradovate Paper agent
  IBKR data (client 50/51) -> strategy.analyze() -> signals
       -> follower_execute() -> place_bracket() -> Tradovate only
```

**Safety guards:**

- Eval gate (circuit breaker + challenge rules) can block execution.
- Market-closed and session checks run before placing orders.
- Auto-flat is disabled — Tradovate bracket orders handle all exits.

---

## 4. Multi-Account Roadmap

The architecture is designed to scale beyond one account:

### Copy Trading (Planned)

```
Tradovate Paper (signal source)
       │
       ├──► Tradovate Paper #2 (50K Eval - Attempt 2)
       ├──► Tradovate Paper #3 (TopStep Combine)
       └──► Future live account
```

Tradovate Paper runs independently — it is both the signal source and execution target. Future follower accounts would copy signals from the primary agent.

Each follower account:
- Has its own state directory, config, and API port.
- Applies its own eval gate rules (different prop firms have different rules).
- Gets its own Telegram label and dashboard view.

### What's Needed

- Per-account config sections in `config.yaml` (structure already exists).
- Lifecycle scripts for each account (based on `tv_paper_eval.sh` template).
- Dashboard account switcher already supports arbitrary accounts via URL parameter.

---

## 5. Config Reference

### Account Section (`config.yaml`)

```yaml
accounts:
  ibkr_virtual:
    display_name: "IBKR Virtual (Archived)"
    badge: "ARCHIVED"
    badge_color: "gray"
    description: "Archived inception test account — $23,248 P&L over 15 days. View at pearlalgo.io/archive/ibkr"
    state_dir: "NQ"
    archived: true
    # No Telegram notifications — archived account, viewable on web app only

  tv_paper:
    display_name: "Tradovate Paper"
    badge: "PAPER"
    badge_color: "orange"
    telegram_prefix: "[TRADOVATE PAPER]"
    description: "Paper trading on Tradovate demo — real bracket orders"
    state_dir: "TV_PAPER_EVAL"
    api_port: 8001
    execution:
      broker: tradovate
      mode: paper

pearl_bot_auto:
  enabled: true
  ema_fast: 5
  ema_slow: 13
  confidence_threshold: 0.40
  entry_triggers:
    - ema_cross
    - vwap_cross
    - vwap_retest
    - trend_momentum
    - trend_breakout
```

### Account Display Config

| Field | Purpose | Example |
|-------|---------|---------|
| `display_name` | Human-readable name shown in UI | `"Tradovate Paper"` |
| `badge` | Short label for status badges | `"PAPER"` |
| `badge_color` | Color for UI badge rendering | `"orange"` |
| `telegram_prefix` | Prefix on all Telegram messages | `"[TRADOVATE PAPER]"` |
| `description` | Tooltip/about text | `"Paper trading on Tradovate demo"` |
| `archived` | Marks account as historical (no agent running) | `true` |

### Internal Identifiers

| Identifier | Type | Used For |
|------------|------|----------|
| `NQ` | State directory | IBKR Virtual archive (`data/archive/ibkr_virtual/`) |
| `TV_PAPER_EVAL` | State directory | Tradovate Paper (`data/agent_state/TV_PAPER_EVAL/`) |
| `?account=tv_paper` | URL parameter | Switch dashboard to Tradovate Paper view |
| `tv_paper` | Config key | References Tradovate Paper in `config.yaml` |

---

## 6. IBKR Client ID Map

The Tradovate Paper agent uses dedicated IBKR client IDs for market data:

| Service | Client ID | Gateway Port |
|---------|-----------|--------------|
| Tradovate Paper agent (trading) | 50 | 4002 |
| Tradovate Paper agent (data) | 51 | 4002 |
| Tradovate Paper chart API | 97 | 4002 |

> **Historical:** IBKR Virtual previously used client IDs 10/11/96. These are now free for reuse.

**Rule:** If you see `"client id already in use"`, another process holds that ID. Restart the conflicting service.
