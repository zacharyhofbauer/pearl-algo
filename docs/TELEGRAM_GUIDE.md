# Telegram Integration Guide

This guide documents the **Telegram Command Handler** (menu-driven control plane) for the PearlAlgo MNQ Agent.

## What runs

- **Command handler service**: `python -m pearlalgo.market_agent.telegram_command_handler`
  - Renders the **main menu** and sub-menus via inline buttons.
  - Reads **agent state** from `data/agent_state/<MARKET>/state.json` and signal history from `data/agent_state/<MARKET>/signals.jsonl`.
  - Uses the project’s lifecycle scripts via `pearlalgo.utils.service_controller.ServiceController` for safe orchestration.

## Quick start

### Requirements

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set in `.env` (see `env.example`)
- Bot created via [@BotFather](https://t.me/botfather)

### Start the command handler

```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/telegram/start_command_handler.sh
```

For background mode:

```bash
./scripts/telegram/start_command_handler.sh --background
```

### (Optional) sync BotFather commands

```bash
python3 scripts/telegram/set_bot_commands.py
```

## Supported commands

The command handler intentionally keeps slash commands minimal:

- `/start`: Show the main dashboard (menu)

Everything else is accessed via the button menus (safer and easier to operate on mobile).

## UI policy (do not drift)

- **Single entrypoint**: `/start` is the dashboard and the menu.
- **No additional slash commands**: keep operations behind inline buttons (mobile-first + safer).
- **BotFather command list**: should only show `/start`. If other commands appear, re-run `python3 scripts/telegram/set_bot_commands.py` and restart the handler.

## Status semantics (how to read the dashboard)

The dashboard is intentionally compact. These indicators should **never contradict** each other:

- **Agent (dot)**: green when the market agent process is running (scanner/trading logic).
- **Gateway (dot)**: green when the IBKR gateway process is running and the API port is listening.
- **Health (dot)**: green when the agent is running and data/connection look healthy; grey when the agent is off.
- **Footer (`Agent: … | Gateway: … | Data: …`)**:
  - **Agent**: uptime since the agent’s `start_time`
  - **Gateway**: service controller gateway status
  - **Data**: age of the latest bar (freshness)

If something looks off, use **🎛️ System** (services) and **🛡️ Health** (data/connection) to confirm, then restart the agent/gateway from **System**.

Tip: Use **🛡️ Health → 🩺 Doctor** for a one-screen diagnostic rollup (agent/gateway/data + key prefs).

## Menu map (operator-facing)

- **Signals & Trades**: recent signals, active trades, signal details
- **Performance**: rollups, exports, diagnostics
- **Health**: agent + gateway connectivity, state freshness, data quality
- **System**: start/stop/restart agent, gateway controls, logs (read-only)
- **Bots**: backtests and report browsing
- **Markets**: select NQ/ES/GC (one UI controlling one market at a time)
- **Settings**: alert/UI preferences and the AI Patch Wizard (if enabled)

## Multi-market usage

The command handler can control multiple market agents (NQ/ES/GC) from one UI:
- Use **Markets** to select the active market
- All reads/writes (state, reports, actions) are scoped to the selected market

## Safety & authorization

- The handler **only responds to the configured chat ID** (`TELEGRAM_CHAT_ID`). Other chats are blocked.
- AI patching blocks sensitive paths (`data/`, `logs/`, `.env`, `.venv/`, `.git/`, etc).

## Troubleshooting

- Restart handler:

```bash
./scripts/telegram/restart_command_handler.sh --background
```

- If you expect backtest recommendations, generate the selection export:

```bash
python3 scripts/backtesting/strategy_selection.py
```
