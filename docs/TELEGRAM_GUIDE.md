# Telegram Integration Guide (Minimal)

This guide documents the **AI-only Telegram interface** for the single-strategy system.

---

## 1. Quick Start

### 1.1 Requirements

- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set in `.env`
- Bot created via [@BotFather](https://t.me/botfather)
- NQ Agent service configured and running

### 1.2 Set Commands via BotFather

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/setcommands`.
3. Select your bot.
4. Paste this command list:
   ```
   analyze - AI strategy report
   help - Show available commands
   ```

### 1.3 Start the Telegram Command Handler

```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/telegram/start_command_handler.sh
```

The handler listens for `/analyze` and `/help` only.

---

## 2. Available Commands

### `/analyze`

Returns a compact AI report with:
- Latest performance summary (from `data/nq_agent_state/exports/performance_*_metrics.json`)
- Single-strategy recommendation (from `data/nq_agent_state/exports/strategy_selection_*.json`)

### `/help`

Shows the minimal command list.

---

## 3. Tips

- If `/analyze` says the selection report is missing, run:
  ```
  python3 scripts/backtesting/strategy_selection.py
  ```
- To update BotFather commands programmatically:
  ```
  python3 scripts/telegram/set_bot_commands.py
  ```
