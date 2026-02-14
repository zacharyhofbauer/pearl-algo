# Account Types & Architecture

> How PearlAlgo manages multiple accounts and data sources. **Trades go directly to Tradovate only — no IBKR Virtual copy or signal forwarding.**

---

## 1. Account Types

PearlAlgo runs two isolated account types side by side:

| | IBKR Virtual | Tradovate Paper |
|---|---|---|
| **Purpose** | Data collection + virtual P&L tracking | Paper trading on Tradovate demo |
| **Broker orders** | None — all P&L is simulated | **Real bracket orders on Tradovate only** (direct) |
| **Signal role** | Runs own strategy (no execution) | **Runs own strategy; orders go straight to Tradovate** |
| **State directory** | `data/agent_state/NQ/` | `data/tradovate/paper/` |
| **API port** | 8000 | 8001 |
| **Telegram label** | `IBKR-VIR` | `TV-PAPER` |
| **Dashboard URL** | `https://pearlalgo.io` | `https://pearlalgo.io/?account=tv_paper` |

### IBKR Virtual

- Connects to Interactive Brokers Gateway for real-time market data.
- Runs the full strategy (`strategy.analyze()`), generates signals, and tracks virtual P&L.
- **No orders are ever sent to any broker.** Execution is disabled; all trades are simulated internally.
- Useful for strategy development and backtesting. **No signals are copied or forwarded to Tradovate.**

### Tradovate Paper (direct execution only)

- **Runs its own strategy** (`pearl_bot_auto` / `strategy.analyze()`) on IBKR market data (client IDs 50/51).
- **Trades go directly to Tradovate** — no IBKR Virtual, no shared signal file, no copy/forward step.
- Places real bracket orders (entry + stop loss + take profit) on the Tradovate demo account.
- All dashboard numbers come from Tradovate fills and equity. Used for prop firm evaluation (e.g. 50K Rapid).

---

## 2. Data Source Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    IBKR Gateway (port 4001)               │
│         Real-time streaming data for ALL accounts         │
└────────────┬─────────────────────────┬───────────────────┘
             │                         │
     ┌───────▼───────┐        ┌───────▼───────┐
     │  IBKR Virtual │        │Tradovate Paper│
     │  (client 10)  │        │  (client 50)  │
     │               │        │               │
     │  strategy +   │        │  strategy +   │
     │  virtual P&L  │        │  direct       │
     │  (no orders)  │        │  Tradovate    │
     └───────────────┘        │  orders only  │
                              └───────┬───────┘
                                      │
                              ┌───────▼───────┐
                              │   Tradovate   │
                              │  (execution   │
                              │   only)       │
                              └───────────────┘
```

**Key point:** IBKR provides market data for both. **Tradovate Paper runs its own strategy and sends orders directly to Tradovate — no signal forwarding from IBKR Virtual.**

### Why IBKR Stays as Data Source

1. **Faster real-time streaming** — IBKR's TWS/Gateway pushes tick-level data with lower latency than Tradovate's WebSocket feed.
2. **Deeper historical data** — Strategy indicators need multi-day bar history that IBKR serves natively.
3. **Strategy consistency** — The strategy was developed and tuned on IBKR data. Switching data sources would invalidate all parameter tuning.
4. **Single data path** — Both accounts see identical market data, ensuring signal parity.

---

## 3. Execution Path (Tradovate Only)

**No signal forwarding.** Each account is independent.

- **IBKR Virtual:** Strategy runs, virtual P&L only. No orders sent anywhere.
- **Tradovate Paper:** Same strategy runs on IBKR data (client 50/51); when a signal is generated it goes **directly** to Tradovate via `follower_execute` → `place_bracket()`. No copy from IBKR Virtual.

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

The architecture is designed to scale beyond two accounts:

### Copy Trading (Planned)

```
IBKR Virtual (signal source)
       │
       ├──► Tradovate Paper #1 (Tradovate Paper 50K Eval - Attempt 1)
       ├──► Tradovate Paper #2 (Tradovate Paper 50K Eval - Attempt 2)
       └──► Tradovate Paper #3 (TopStep Combine)
```

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
    display_name: "IBKR Virtual"
    badge: "VIRTUAL"
    badge_color: "blue"
    telegram_prefix: "[IBKR VIRTUAL]"
    description: "Virtual P&L tracking on IBKR — no broker orders"
    state_dir: "NQ"
    api_port: 8000
    signal_role: "writer"

  tv_paper:
    display_name: "Tradovate Paper"
    badge: "PAPER"
    badge_color: "orange"
    telegram_prefix: "[TRADOVATE PAPER]"
    description: "Paper trading on Tradovate demo — real bracket orders"
    state_dir: "TV_PAPER_EVAL"
    api_port: 8001
    signal_role: "follower"
    execution:
      broker: tradovate
      mode: paper
```

### Account Display Config

| Field | Purpose | Example |
|-------|---------|---------|
| `display_name` | Human-readable name shown in UI | `"Tradovate Paper"` |
| `badge` | Short label for status badges | `"PAPER"` |
| `badge_color` | Color for UI badge rendering | `"orange"` |
| `telegram_prefix` | Prefix on all Telegram messages | `"[TRADOVATE PAPER]"` |
| `description` | Tooltip/about text | `"Paper trading on Tradovate demo"` |

### Internal Identifiers

| Identifier | Type | Used For |
|------------|------|----------|
| `NQ` | State directory | IBKR Virtual (`data/agent_state/NQ/`) |
| `TV_PAPER_EVAL` | State directory | Tradovate Paper (`data/agent_state/TV_PAPER_EVAL/`) |
| `?account=tv_paper` | URL parameter | Switch dashboard to Tradovate Paper view |
| `ibkr_virtual` | Config key | References IBKR Virtual in `config.yaml` |
| `tv_paper` | Config key | References Tradovate Paper in `config.yaml` |

---

## 6. IBKR Client ID Map

Each account uses dedicated IBKR client IDs to avoid conflicts:

| Service | Client ID | Gateway Port |
|---------|-----------|--------------|
| IBKR Virtual agent (trading) | 10 | 4002 |
| IBKR Virtual agent (data) | 11 | 4002 |
| IBKR Virtual chart API | 96 | 4002 |
| Tradovate Paper agent (trading) | 50 | 4002 |
| Tradovate Paper agent (data) | 51 | 4002 |
| Tradovate Paper chart API | 97 | 4002 |

**Rule:** If you see `"client id already in use"`, another process holds that ID. Restart the conflicting service.
