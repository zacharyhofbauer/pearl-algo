# Account Types & Architecture

> How PearlAlgo manages multiple accounts, data sources, and signal forwarding.

---

## 1. Account Types

PearlAlgo runs two isolated account types side by side:

| | IBKR Virtual | Tradovate Paper |
|---|---|---|
| **Purpose** | Data collection + virtual P&L tracking | Paper trading on Tradovate demo |
| **Broker orders** | None — all P&L is simulated | Real bracket orders on Tradovate demo account |
| **Signal role** | Writer (generates signals) | Follower (reads forwarded signals) |
| **State directory** | `data/agent_state/NQ/` | `data/agent_state/MFFU_EVAL/` |
| **API port** | 8000 | 8001 |
| **Telegram label** | `[IBKR VIRTUAL]` | `[TRADOVATE PAPER]` |
| **Dashboard URL** | `https://pearlalgo.io` | `https://pearlalgo.io/?account=mffu` |

### IBKR Virtual

- Connects to Interactive Brokers Gateway for real-time market data.
- Runs the full strategy (`strategy.analyze()`), generates signals, and tracks virtual P&L.
- **No orders are ever sent to the broker.** Execution is disabled; all trades are simulated internally.
- Useful for strategy development, backtesting validation, and as the canonical signal source.

### Tradovate Paper

- Receives forwarded signals from IBKR Virtual (does NOT run its own strategy).
- Places real bracket orders (entry + stop loss + take profit) on a Tradovate demo/paper account.
- All dashboard numbers come directly from Tradovate fills and equity — no virtual tracking.
- Used for prop firm evaluation attempts (e.g., MFFU 50K Rapid).

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
     │  strategy +   │        │  data from    │
     │  virtual P&L  │        │  IBKR only    │
     └───────┬───────┘        └───────┬───────┘
             │                        │
             │  shared_signals.jsonl   │
             └────────────►───────────┘
                                      │
                              ┌───────▼───────┐
                              │   Tradovate    │
                              │  (execution    │
                              │   only)        │
                              └───────────────┘
```

**Key point:** IBKR provides market data for **both** accounts. Tradovate is execution-only for Tradovate Paper accounts.

### Why IBKR Stays as Data Source

1. **Faster real-time streaming** — IBKR's TWS/Gateway pushes tick-level data with lower latency than Tradovate's WebSocket feed.
2. **Deeper historical data** — Strategy indicators need multi-day bar history that IBKR serves natively.
3. **Strategy consistency** — The strategy was developed and tuned on IBKR data. Switching data sources would invalidate all parameter tuning.
4. **Single data path** — Both accounts see identical market data, ensuring signal parity.

---

## 3. Signal Forwarding

IBKR Virtual is the **writer**; Tradovate Paper is the **follower**.

```
IBKR Virtual (WRITER)                 Tradovate Paper (FOLLOWER)
  IBKR -> strategy.analyze()            _read_shared_signals()
       |                                      |
  shared_signals.jsonl  ----------->  dedup (direction, bar_ts)
       |                                      |
  virtual P&L + [IBKR VIRTUAL] TG      eval gate -> Tradovate bracket order
                                              |
                                        [TRADOVATE PAPER] Telegram
```

**How it works:**

1. IBKR Virtual runs `strategy.analyze()` on every bar and writes signals to `data/shared_signals.jsonl`.
2. Tradovate Paper polls the shared file for new signals.
3. Signals are deduped by `(direction, bar_timestamp)` to prevent double-entry.
4. The eval gate (circuit breaker + challenge rules) decides whether to forward to Tradovate.
5. If approved, a bracket order (OSO) is placed on Tradovate.

**Safety guards:**

- Shared signals file is cleared on Tradovate Paper restart (no replay of stale signals).
- Market-closed check runs before processing any forwarded signal.
- Auto-flat is disabled — Tradovate bracket orders handle all exits.

---

## 4. Multi-Account Roadmap

The architecture is designed to scale beyond two accounts:

### Copy Trading (Planned)

```
IBKR Virtual (signal source)
       │
       ├──► Tradovate Paper #1 (MFFU 50K Eval - Attempt 1)
       ├──► Tradovate Paper #2 (MFFU 50K Eval - Attempt 2)
       └──► Tradovate Paper #3 (TopStep Combine)
```

Each follower account:
- Has its own state directory, config, and API port.
- Applies its own eval gate rules (different prop firms have different rules).
- Gets its own Telegram label and dashboard view.

### What's Needed

- Per-account config sections in `config.yaml` (structure already exists).
- Lifecycle scripts for each account (based on `mffu_eval.sh` template).
- Dashboard account switcher already supports arbitrary accounts via URL parameter.

---

## 5. Config Reference

### Account Section (`config.yaml`)

```yaml
accounts:
  inception:
    display_name: "IBKR Virtual"
    badge: "VIRTUAL"
    badge_color: "blue"
    telegram_prefix: "[IBKR VIRTUAL]"
    description: "Virtual P&L tracking on IBKR — no broker orders"
    state_dir: "NQ"
    api_port: 8000
    signal_role: "writer"

  mffu:
    display_name: "Tradovate Paper"
    badge: "PAPER"
    badge_color: "orange"
    telegram_prefix: "[TRADOVATE PAPER]"
    description: "Paper trading on Tradovate demo — real bracket orders"
    state_dir: "MFFU_EVAL"
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
| `MFFU_EVAL` | State directory | Tradovate Paper (`data/agent_state/MFFU_EVAL/`) |
| `?account=mffu` | URL parameter | Switch dashboard to Tradovate Paper view |
| `inception` | Config key | References IBKR Virtual in `config.yaml` |
| `mffu` | Config key | References Tradovate Paper in `config.yaml` |

---

## 6. IBKR Client ID Map

Each account uses dedicated IBKR client IDs to avoid conflicts:

| Service | Client ID | Gateway Port |
|---------|-----------|--------------|
| IBKR Virtual agent (trading) | 10 | 4001 |
| IBKR Virtual agent (data) | 11 | 4001 |
| IBKR Virtual chart API | 96 | 4001 |
| Tradovate Paper agent (trading) | 50 | 4001 |
| Tradovate Paper agent (data) | 51 | 4001 |
| Tradovate Paper chart API | 97 | 4001 |

**Rule:** If you see `"client id already in use"`, another process holds that ID. Restart the conflicting service.
