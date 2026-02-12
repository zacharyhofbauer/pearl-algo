# PEARLalgo Cheat Sheet

> Quick reference for daily operations. Most-used commands first.

---

## 1. Daily Commands

```bash
# Start/stop everything
./pearl.sh start                # Gateway -> Agent -> Telegram -> Chart
./pearl.sh stop                 # Stop all services
./pearl.sh restart              # Restart all
./pearl.sh status               # Full status dashboard
./pearl.sh quick                # One-liner: Gateway OK | Agent OK | ...

# Tradovate Paper (prop firm eval -- most used)
./scripts/lifecycle/tv_paper_eval.sh restart --background   # Clean restart (kills stale processes)
./scripts/lifecycle/tv_paper_eval.sh start --background     # Start agent + API
./scripts/lifecycle/tv_paper_eval.sh stop                   # Stop everything
./scripts/lifecycle/tv_paper_eval.sh status                 # Check status

# Individual services
./pearl.sh gateway start|stop|status
./pearl.sh agent start|stop|status         # IBKR Virtual (NQ)
./pearl.sh tv_paper start|stop|restart|status  # Tradovate Paper
./pearl.sh telegram start|stop|status
./pearl.sh chart start|stop|status         # Web app (pearlalgo.io)
./pearl.sh chart deploy                    # Build + restart (after code changes)
./pearl.sh chart build                     # Build only (no restart)
./pearl.sh tunnel start|stop|status        # Cloudflare tunnel
```

**After any code change:**
- Web app (frontend): `./pearl.sh chart deploy` (builds + restarts in production mode)
- Tradovate Paper (backend): `./scripts/lifecycle/tv_paper_eval.sh restart --background`
- IBKR Virtual: `./pearl.sh restart`

---

## 2. Tradovate Paper — 50K Rapid Evaluation

Pearl runs two isolated accounts:
- **IBKR Virtual** (port 8000): Virtual PnL on IBKR, no real orders
- **Tradovate Paper** (port 8001): Real orders on Tradovate paper (demo)

### Signal Forwarding (IBKR Virtual -> Tradovate Paper)

IBKR Virtual generates signals. Tradovate Paper reads them from a shared file -- it does NOT run its own strategy.

```
IBKR Virtual (WRITER)                 Tradovate Paper (FOLLOWER)
  IBKR -> strategy.analyze()            _read_shared_signals()
       |                                      |
  shared_signals.jsonl  ----------->  dedup (direction, bar_ts)
       |                                      |
  virtual PnL + [IBKR VIRTUAL] TG      eval gate -> Tradovate bracket order
                                              |
                                        [TRADOVATE PAPER] Telegram
```

**Safety guards:**
- Shared signals file cleared on Tradovate Paper restart (no replay)
- Market-closed check before processing any forwarded signal
- Auto-flat disabled (Tradovate bracket orders handle exits)

### Dashboard: Tradovate Only

Every number on the Tradovate Paper dashboard comes from Tradovate. No virtual tracking.

| Panel | Source |
|-------|--------|
| Header P&L | Today's FIFO-paired fills (commission-adjusted) |
| Header W/L | Today's fill wins/losses (filtered to trading day) |
| Positions | `tradovate get_positions()` |
| Recent Trades | `tradovate get_fills()` (FIFO paired) |
| Performance | FIFO-paired fills per period, commission-adjusted against equity |
| Challenge | Tradovate equity + fills |
| Risk Metrics | Tradovate fills |
| Analytics | Tradovate fills |
| Chart | IBKR (client ID 97) |

Fills persist to `tradovate_fills.json` across sessions (Tradovate clears `/fill/list` daily).

**Commission handling:** Tradovate fills don't include fees. The Tradovate Paper dashboard derives the per-trade commission from the gap between total fill P&L and actual Tradovate equity, then deducts it from all period summaries so numbers match the broker.

### Evaluation Rules

| Rule | Threshold |
|------|-----------|
| Start Balance | $50,000 |
| Profit Target | $3,000 |
| Max Loss (EOD trailing) | $2,000 |
| Drawdown Floor Lock | None (eval has no lock; sim_funded locks at $100) |
| Max Contracts | 5 mini / 50 micro |
| Max Positions | 20 |
| Consistency | 50% (no single day > 50% of profit) |
| Min Trading Days | 2 |
| Trading Hours | 6 PM - 4:10 PM ET |
| T1 News | Allowed during eval |
| Hedging | Prohibited |

### Reset Procedure

1. Adjust Tradovate balance: Settings > Accounts > Modify Balance
2. `rm data/agent_state/TV_PAPER_EVAL/challenge_state.json`
3. `rm -f data/agent_state/TV_PAPER_EVAL/signals.jsonl data/agent_state/TV_PAPER_EVAL/performance.json data/agent_state/TV_PAPER_EVAL/tradovate_fills.json`
4. `./scripts/lifecycle/tv_paper_eval.sh restart --background`

### Tradovate Credentials

In `~/.config/pearlalgo/secrets.env` (never committed):
```
TRADOVATE_USERNAME=...
TRADOVATE_PASSWORD=...
TRADOVATE_CID=...
TRADOVATE_SEC=...
```

---

## 3. Web Dashboard (pearlalgo.io)

```bash
# Local
http://localhost:3001                        # Web app
http://localhost:3001?account=tv_paper           # Tradovate Paper dashboard

# Public
https://pearlalgo.io                         # IBKR Virtual
https://pearlalgo.io/?account=tv_paper           # Tradovate Paper
```

Account switcher dropdown in the header bar toggles between accounts.

### Key Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `IB_CLIENT_ID_LIVE_CHART` | `96` | IBKR chart client ID (IBKR Virtual) |
| `PEARL_API_KEY` | secrets.env | API authentication |
| `PEARL_API_PORT` | `8000` | IBKR Virtual API |
| `PEARL_CHART_PORT` | `3001` | Next.js web app |

Tradovate Paper uses client ID 97, set by `tv_paper_eval.sh`.

### Tunnel Commands

```bash
./pearl.sh tunnel status       # Check public access
./pearl.sh tunnel restart      # Restart tunnel
./pearl.sh tunnel logs         # View logs
```

First-time setup: `sudo ./scripts/setup-cloudflared-service.sh`

---

## 4. Troubleshooting

| Problem | Fix |
|---------|-----|
| Tradovate Paper dashboard wrong data | `./scripts/lifecycle/tv_paper_eval.sh restart --background` |
| No signals forwarded | Check `logs/agent_NQ.log` -- `NoOpportunity` = normal (no crossover) |
| Chart shows CACHE not LIVE | Restart via lifecycle script (fixes client ID conflicts) |
| pearlalgo.io unreachable | `./pearl.sh tunnel status` then `sudo ./scripts/setup-cloudflared-service.sh` |
| No market data | `./scripts/gateway/gateway.sh status` -- gateway may be down |
| Telegram not responding | `./pearl.sh telegram status` then `./pearl.sh telegram restart` |
| "client id already in use" | Another process holds the IBKR client ID -- restart the conflicting service |
| Tradovate Paper signals on restart | Fixed: shared file cleared on startup + market-closed guard |
| Fills show 0 after restart | Normal if market closed -- fills persist in `tradovate_fills.json` |
| Telegram shows wrong attempt # | Fixed: Telegram now uses `TvPaperEvaluationTracker` (not `ChallengeTracker`) for Tradovate Paper accounts |
| Header P&L doesn't match Today | Fixed: header now uses today's fill-paired P&L (was using all-time equity delta) |
| All Time P&L doesn't match Tradovate | Fixed: commission auto-derived from equity vs fill gap and deducted from all periods |

### Logs

```bash
tail -f logs/agent_NQ.log          # IBKR Virtual agent
tail -f logs/agent_TV_PAPER_EVAL.log   # Tradovate Paper agent
tail -f logs/api_TV_PAPER_EVAL.log     # Tradovate Paper API server
tail -f logs/web_app.log           # Next.js
```

---

## 5. Architecture Reference

### File Locations

| What | Where |
|------|-------|
| IBKR Virtual config | `config/config.yaml` |
| Tradovate Paper config | `config/markets/tv_paper_eval.yaml` |
| Credentials | `~/.config/pearlalgo/secrets.env` |
| Env defaults | `.env` |
| IBKR Virtual state | `data/agent_state/NQ/` |
| Tradovate Paper state | `data/agent_state/TV_PAPER_EVAL/` |
| Signal forwarding | `data/shared_signals.jsonl` |
| Tradovate Paper fills (persistent) | `data/agent_state/TV_PAPER_EVAL/tradovate_fills.json` |
| Scripts | `scripts/lifecycle/`, `scripts/gateway/`, `scripts/telegram/` |

### IBKR Client ID Map

| Service | Client ID | Port |
|---------|-----------|------|
| IBKR Virtual agent (trading) | 10 | 4002 |
| IBKR Virtual agent (data) | 11 | 4002 |
| IBKR Virtual chart API | 96 | 4002 |
| Tradovate Paper agent (trading) | 50 | 4002 |
| Tradovate Paper agent (data) | 51 | 4002 |
| Tradovate Paper chart API | 97 | 4002 |

### Key Code Files

| File | Purpose | Affects |
|------|---------|---------|
| `service.py` | Agent orchestrator (inherits `ServiceNotificationsMixin`), signal forwarding, Tradovate polling. Virtual trade exits delegated to `virtual_trade_manager.py` | Both |
| `tv_paper_eval_tracker.py` | Challenge state tracking (eval: fixed floor $48K, no lock; sim_funded: intraday trailing, locks at $100) | Tradovate Paper |
| `tradovate/adapter.py` | Execution + `get_account_summary()` | Tradovate Paper |
| `tradovate/client.py` | REST/WS client (`get_fills`, `get_positions`) | Tradovate Paper |
| `trading_circuit_breaker.py` | Risk management + eval gate | Both |
| `config_loader.py` | Config loading, signal_forwarding defaults | Both |
| `tv_paper_eval.sh` | Tradovate Paper lifecycle (port cleanup, restart) | Tradovate Paper |
| `api_server.py` | API server (auth, rate-limiting, `StateReader`). Header/performance stats use today's fills with auto-derived commission deduction | Dashboard |
| `tradovate/utils.py` | FIFO fill pairing for Tradovate trades | Tradovate Paper |
| `telegram_command_handler.py` | Telegram bot commands. Uses `_detect_tv_paper_account()` to pick correct tracker | Both |
| `ChallengePanel.tsx` | Tradovate Paper eval display | Dashboard |
| `AnalyticsPanel.tsx` | Sessions, hours, duration, calendar | Dashboard |

### Isolation Model

| Component | IBKR Virtual | Tradovate Paper |
|-----------|-----------|------|
| Config | `config/config.yaml` | `config/markets/tv_paper_eval.yaml` |
| State dir | `data/agent_state/NQ/` | `data/agent_state/TV_PAPER_EVAL/` |
| API port | 8000 | 8001 |
| Signal gen | `strategy.analyze()` | Reads shared file |
| Dashboard data | `signals.jsonl` + `performance.json` | Tradovate API |
| Execution | Disabled (virtual) | Tradovate paper (armed) |
| Telegram label | `[IBKR VIRTUAL]` | `[TRADOVATE PAPER]` |

**Rule:** `config.yaml` changes only affect IBKR Virtual. `tv_paper_eval.yaml` only affects Tradovate Paper. `service.py` changes affect both.

---

## 6. First-Time Setup

### Python Environment

```bash
cd ~/PearlAlgoProject
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment Files

```bash
cp env.example .env
# Edit .env with your IBKR ports, client IDs, etc.
```

Key `.env` variables:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
IBKR_HOST=127.0.0.1
IBKR_PORT=4002
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11
IB_CLIENT_ID_LIVE_CHART=96
PEARLALGO_DATA_PROVIDER=ibkr
```

### Node.js (for web app)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
cd pearlalgo_web_app && npm install
```

### Cloudflare Tunnel

```bash
sudo ./scripts/setup-cloudflared-service.sh   # One-time: auto-starts on boot
```

### Telegram

```bash
# Verify config
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID
python3 scripts/testing/test_all.py telegram
```

---

## Key Concepts

- **StrategySessionOpen**: When the strategy generates signals (config session window)
- **FuturesMarketOpen**: When CME data flows (Sun 6 PM ET - Fri 5 PM ET, with daily 5-6 PM break)
- **Signal forwarding**: IBKR Virtual writes signals, Tradovate Paper reads them. One-way, deduped by `(direction, bar_timestamp)`
- **Tradovate bracket order**: Entry + stop loss + take profit placed as OSO (one-sends-other)
- **FIFO fill pairing**: Tradovate fills matched oldest-first to compute per-trade P&L

---

## Audit Quick Reference

> Full docs: [`docs/AUDIT_SYSTEM.md`](AUDIT_SYSTEM.md) and [`docs/UI_AUDIT_GUIDE.md`](UI_AUDIT_GUIDE.md)

### Telegram Commands

```
/audit                    # Open interactive audit menu
/audit trades [7d|30d]    # Trade summary
/audit signals [7d|30d]   # Signal decisions (generated vs rejected)
/audit health [7d|30d]    # System health (restarts, drops, trips)
/audit reconcile          # Agent vs broker P&L comparison
/audit export             # Download CSV
```

### API Endpoints

```
GET /api/audit/events           # Full event log (filterable)
GET /api/audit/equity-history   # Daily balance snapshots
GET /api/audit/reconciliation   # Agent vs broker P&L
GET /api/audit/signals          # Signal generation summary
GET /api/audit/export           # CSV export
```

### Web Dashboard

Click the **Audit** tab in the dashboard navigation:

| Sub-tab | Shows |
|---------|-------|
| Trade Ledger | All trades, filterable + exportable |
| Signal Decisions | Generated vs rejected signals |
| System Events | Timeline of starts, stops, drops, trips |
| Equity History | Daily balance chart per account |
| Reconciliation | Agent P&L vs broker P&L |

### Direct SQL

```bash
# Replace <MARKET> with NQ, TV_PAPER_EVAL, etc.
sqlite3 data/agent_state/<MARKET>/trades.db "SELECT * FROM audit_events WHERE event_type='trade_entry' ORDER BY timestamp DESC LIMIT 10;"
```
