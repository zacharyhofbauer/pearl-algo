# Telegram Integration Guide

This guide is the **canonical reference** for using Telegram with the NQ Agent.
It combines quick start steps, command setup, and command behavior.

---

## 1. Quick Start: Get Commands Working

### 1.1 Requirements

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set in `.env`
- Bot created via [@BotFather](https://t.me/botfather)
- NQ Agent service configured and working

### 1.2 Set Commands via BotFather (recommended)

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/setcommands`.
3. Select your bot.
4. Paste this command list:
   ```
   status - Get current agent status
   pause - Pause the trading agent
   resume - Resume the trading agent
   signals - Show recent signals
   performance - Show performance metrics
   help - Show available commands
   ```
5. BotFather will confirm the commands are set.

### 1.3 Start the Telegram Command Handler

The command handler is a **separate service** that listens for `/status`, `/signals`, etc.

#### Option 1: Standalone (recommended for testing)

```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.telegram_command_handler
```

You should see something like:

```text
Starting Telegram command handler...
Listening for commands from chat ID: YOUR_CHAT_ID
Press Ctrl+C to stop
```

#### Option 2: Use the helper script

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/telegram/start_command_handler.sh
```

This script:
- Changes to the project root
- Activates `.venv` if present
- Verifies `pearlalgo` is importable
- Starts `pearlalgo.nq_agent.telegram_command_handler`

### 1.4 Verify Commands Work

1. Start the command handler (see above).
2. In Telegram, send `/status`.
3. You should receive an **Agent Status** card with inline buttons.

If you do **not** get a response:
- Check the handler is running: `./scripts/telegram/check_command_handler.sh`
- Check logs: `tail -f logs/telegram_handler.log` (if you start it with `nohup`)
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct.

---

## 2. Optional: Set Commands via API

Instead of BotFather, you can set commands using the Telegram API.

A helper script is provided:

```bash
cd ~/pearlalgo-dev-ai-agents
python3 scripts/telegram/set_bot_commands.py
```

Internally it uses `python-telegram-bot` and calls `Bot.set_my_commands()` with the same command list.

---

## 3. Available Commands and Behavior

Once the command handler is running and commands are configured, the bot supports these commands.

### 3.1 `/start` and `/help`

- Shows basic bot information and available commands.
- Intended primarily for you (authorized chat ID).

### 3.2 `/status`

Returns the current agent status, including:

- Running / stopped state
- Cycle count
- Signal count
- Buffer size (bars loaded)
- Inline buttons:
  - **Pause** – placeholder action (informational text for now)
  - **Performance** – quick link to `/performance`
  - **Signals** – quick link to `/signals`

### 3.3 `/signals`

- Shows the last **10 recent trading signals**.
- For each signal, includes:
  - Type (e.g., breakout)
  - Direction (LONG)
  - Entry price
  - Current status (`generated`, `entered`, `exited`, `expired`).
- Data is read from `data/nq_agent_state/signals.jsonl` via the `state_manager` and `performance_tracker`.

### 3.4 `/performance`

- Shows **7‑day performance metrics**:
  - Total signals and exited signals
  - Win / loss counts
  - Win rate percentage
  - Total P&L and average P&L
- Uses the same performance metrics as the periodic Telegram summaries.

### 3.5 `/pause` and `/resume`

- Currently **informational only**:
  - They confirm the command was received.
  - They indicate that direct pause/resume requires service‑level integration.
- The actual pause/resume of the agent is still controlled via lifecycle scripts:
  - `./scripts/lifecycle/start_nq_agent_service.sh`
  - `./scripts/lifecycle/stop_nq_agent_service.sh`

---

## 4. What Needs the Command Handler vs. What Does Not

### 4.1 Works without the command handler

These notifications come directly from the NQ Agent Service via `NQAgentTelegramNotifier`:

- Startup and shutdown notifications
- Signal notifications
- Status updates
- Heartbeat messages
- Error and circuit‑breaker alerts

### 4.2 Requires the command handler

These features require the command handler service to be running:

- `/status`, `/signals`, `/performance`, `/help`, `/pause`, `/resume`
- Inline button callbacks (Pause, Performance, Signals)

If commands are unresponsive but you still get status/heartbeat messages, it almost always means the command handler is not running.

---

## 5. Security and Authorization

- The command handler checks that the incoming chat ID matches `TELEGRAM_CHAT_ID`.
- Unauthorized chats receive a simple "Unauthorized access" message.
- Secrets (bot token, chat ID) must remain in `.env` and **never** be committed.

---

## 6. Troubleshooting Cheat Sheet

- **No command responses:**
  - Run `./scripts/telegram/check_command_handler.sh`.
  - If not running, start it with `./scripts/telegram/start_command_handler.sh`.
- **`python-telegram-bot` import errors:**
  - Install inside your venv: `pip install python-telegram-bot`.
- **Handler crashes on start:**
  - Check logs (`logs/telegram_handler.log` if using `nohup`).
  - Verify `.env` is loaded and `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are set.
- **Commands missing in Telegram UI:**
  - Re‑run `/setcommands` in BotFather or `scripts/telegram/set_bot_commands.py`.

This file is the authoritative reference for Telegram integration. Other Telegram docs should defer to this guide.
