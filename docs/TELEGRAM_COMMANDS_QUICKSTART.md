# Telegram Bot Commands - Quick Start

## ⚠️ Important: Command Handler Must Be Running

The commands (`/status`, `/signals`, etc.) **only work when the command handler service is running**.

Your bot can send notifications (startup, shutdown, signals) without the handler, but to **receive and respond to commands**, you need to start the handler service.

## How to Start Command Handler

### Option 1: Run in Foreground (Recommended for testing)

```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.telegram_command_handler
```

You should see:
```
Starting Telegram command handler...
Listening for commands from chat ID: YOUR_CHAT_ID
Press Ctrl+C to stop
```

### Option 2: Run in Background

```bash
cd ~/pearlalgo-dev-ai-agents
nohup python3 -m pearlalgo.nq_agent.telegram_command_handler > logs/telegram_handler.log 2>&1 &
```

Check if it's running:
```bash
ps aux | grep telegram_command_handler
```

## Verify It's Working

1. **Start the command handler** (see above)
2. **Send `/status` in Telegram**
3. **You should get a response** with agent status

If you don't get a response:
- Check that handler is running: `ps aux | grep telegram_command_handler`
- Check logs: `tail -f logs/telegram_handler.log`
- Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set correctly

## What Works Without Handler

These work automatically (no handler needed):
- ✅ Startup notifications
- ✅ Shutdown notifications  
- ✅ Signal notifications
- ✅ Status updates
- ✅ Heartbeat messages
- ✅ Error alerts

## What Requires Handler

These require the handler service to be running:
- ❌ `/status` command
- ❌ `/signals` command
- ❌ `/performance` command
- ❌ `/pause` / `/resume` commands
- ❌ Inline button callbacks

## Troubleshooting

**No response to commands?**
- Handler not running → Start it (see above)
- Wrong chat ID → Check TELEGRAM_CHAT_ID matches your Telegram chat ID
- Bot token invalid → Verify TELEGRAM_BOT_TOKEN in .env

**Handler crashes?**
- Check logs for errors
- Verify python-telegram-bot is installed: `pip install python-telegram-bot`
- Check state files exist: `ls -la data/nq_agent_state/`

**Commands set but not showing?**
- Set commands via BotFather: `/setcommands` → Select bot → Send command list
- Or run: `python3 scripts/telegram/set_bot_commands.py`


