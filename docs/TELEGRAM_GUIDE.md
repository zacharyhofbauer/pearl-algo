# Telegram Integration Guide

This guide documents the **Telegram Command Handler** for the PearlAlgo trading agent.

## What runs

- **Command handler service**: `python -m pearlalgo.telegram.main`
  - Renders the **main menu** and command responses via inline buttons.
  - Fetches **agent state** from the API server (`/api/state`).
  - All commands are read-only except Start/Stop/Kill Switch/Flatten.

## Quick start

### Requirements

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set in `~/.config/pearlalgo/secrets.env` or `.env`
- Bot created via [@BotFather](https://t.me/botfather)

### Start the command handler

```bash
cd ~/PearlAlgoProject
./pearl.sh telegram start
```

### Sync BotFather commands

```bash
python3 scripts/telegram/set_bot_commands.py
```

## Commands

The bot mirrors the web app dashboard at pearlalgo.io:

### Monitoring

| Command | Description | Dashboard Equivalent |
|---------|-------------|---------------------|
| `/status` | Balance, P&L, positions, AI headline | AccountStrip + header badges |
| `/stats` | Performance by period (Today/24h/72h/30d/All Time) | Stats tab |
| `/trades` | Recent trade history with direction, P&L, duration | History tab |

### Diagnostics

| Command | Description | Dashboard Equivalent |
|---------|-------------|---------------------|
| `/health` | System health, connectivity, data quality, circuit breaker | Header badges + system panel |
| `/doctor` | Risk metrics, direction breakdown, ML filter, shadow mode | Stats tab (risk + analytics) |
| `/signals` | Signal rejections (24h), last signal decision | Signals tab |

### Controls

| Command | Description |
|---------|-------------|
| `/settings` | Current configuration (symbol, timeframe, execution) |
| `/menu` | Main menu with inline buttons |
| `/help` | List all commands |

### Emergency (via menu buttons)

- **Kill Switch** — Immediately stop agent + cancel all orders
- **Flatten All** — Close all open positions at market

Both require confirmation before executing.

## Menu layout

```
📊 Status  │  📈 Stats   │  📋 Trades
💚 Health  │  🩺 Doctor  │  🧠 Signals
⏹ Stop / ▶️ Start     │  ⚙️ Settings
🚨 Kill Switch         │  📋 Flatten All
```

## Push notifications

The agent also sends automatic push notifications for:

- **Trade entries/exits** — Direction, P&L, exit reason
- **Status updates** — Periodic dashboard card with balance, P&L, recent exits
- **Circuit breaker alerts** — When risk limits are hit
- **Data quality alerts** — Stale data, connection issues
- **Daily/weekly summaries** — Performance rollups

Push notification format:
```
🐚 PEARL — Tradovate Paper
MNQ • 06:30 PM ET

Agent 🟢  GW 🟢  Data 🟢
Market 🔴  Session 🔴
🧠 Bandit disabled · Ctx shadow · ML shadow

Today: 🔴 -$645.91
7W/4L · 43% WR
30d: 🟢 +$2,856.70 (112W/122L · 48%)

Recent:
🟢 +$150.00 · 🔵 LONG · take profit
🔴 -$89.50 · 🟣 SHORT · stop loss

🩺 MNQ v0.2.4 | A:ON G:OK D:3s C:5s
```

## Safety & authorization

- The handler **only responds to the configured chat ID** (`TELEGRAM_CHAT_ID`). Other chats are blocked.
- Dangerous actions (Kill Switch, Flatten) require confirmation.

## Troubleshooting

```bash
# Check status
./pearl.sh telegram status

# Restart
./pearl.sh telegram stop && ./pearl.sh telegram start

# View logs
tail -50 logs/telegram_handler.log
```

## Architecture

- **Telegram handlers** → fetch from Agent API (`/api/state`) via HTTP
- **Push notifications** → sent by `MarketAgentTelegramNotifier` during agent runtime
- **No direct file access** — handlers are API-only, no state file reads
