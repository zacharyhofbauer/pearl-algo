# Telegram Bot Commands Setup Guide

## Overview

This guide explains how to add interactive commands and features to your Telegram bot using BotFather.

## Step 1: Set Commands via BotFather

1. **Open Telegram** and start a chat with [@BotFather](https://t.me/botfather)

2. **Send `/setcommands`** to BotFather

3. **Select your bot** from the list

4. **Send the following command list:**
   ```
   status - Get current agent status
   pause - Pause the trading agent
   resume - Resume the trading agent
   signals - Show recent signals
   performance - Show performance metrics
   help - Show available commands
   ```

5. **BotFather will confirm** the commands are set

## Step 2: Manual Setup (Alternative)

You can also set commands manually via Telegram API. Here's a Python script to do it:

```python
from telegram import Bot, BotCommand

bot_token = "YOUR_BOT_TOKEN"
bot = Bot(token=bot_token)

commands = [
    BotCommand('status', 'Get current agent status'),
    BotCommand('pause', 'Pause the trading agent'),
    BotCommand('resume', 'Resume the trading agent'),
    BotCommand('signals', 'Show recent signals'),
    BotCommand('performance', 'Show performance metrics'),
    BotCommand('help', 'Show available commands'),
]

bot.set_my_commands(commands)
print("Commands set successfully!")
```

## Step 3: Install Required Package

Make sure you have `python-telegram-bot` installed:

```bash
pip install python-telegram-bot
```

## Step 4: Set Commands Programmatically (Optional)

You can use the provided script to set commands:

```bash
cd ~/pearlalgo-dev-ai-agents
python3 scripts/telegram/set_bot_commands.py
```

This will automatically set all commands via the Telegram API.

## Step 5: Start Command Handler Service

A command handler has been implemented at `src/pearlalgo/nq_agent/telegram_command_handler.py`.

### To start the command handler:

**Option 1: Run as standalone service (Recommended)**
```bash
cd ~/pearlalgo-dev-ai-agents
python3 -m pearlalgo.nq_agent.telegram_command_handler
```

**Option 2: Use the helper script**
```bash
./scripts/telegram/start_command_handler.sh
```

The command handler runs separately from the main trading agent and listens for incoming Telegram messages and commands.

### Option 2: Integrated Command Handler

Add command handling directly to the main service:

**Benefits:**
- Single process
- Direct access to service state

**Drawbacks:**
- Adds complexity to main service
- Requires threading/async handling

## Commands to Implement

### `/status`
Shows current agent status (same as enhanced status message)

### `/pause`
Pauses the trading agent

### `/resume`
Resumes the trading agent

### `/signals`
Shows recent signals with details

### `/performance`
Shows performance metrics (7-day, all-time)

### `/help`
Shows list of available commands

## Inline Keyboard Buttons

In addition to commands, you can add inline keyboard buttons to notifications:

**Example: Add buttons to status messages:**
```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [
    [InlineKeyboardButton("⏸️ Pause", callback_data='pause'),
     InlineKeyboardButton("▶️ Resume", callback_data='resume')],
    [InlineKeyboardButton("📊 Status", callback_data='status'),
     InlineKeyboardButton("📈 Performance", callback_data='performance')],
]
reply_markup = InlineKeyboardMarkup(keyboard)
```

## Available Commands

Once the command handler is running, you can use these commands in Telegram:

### `/start` or `/help`
Shows available commands and bot information

### `/status`
Get current agent status, including:
- Running/stopped status
- Cycle count
- Signal count
- Buffer size
- Quick action buttons (Pause/Resume)

### `/signals`
Show the last 10 recent trading signals with:
- Signal type and direction
- Entry price
- Current status (generated, entered, exited, expired)

### `/performance`
Show 7-day performance metrics:
- Total signals vs exited signals
- Win/loss count
- Win rate percentage
- Total P&L
- Average P&L

### `/pause` and `/resume`
Currently informational (shows note that service integration needed for direct control)

## How It Works

1. **Command Handler Service**: Runs separately, listens for Telegram messages
2. **State Files**: Reads agent state from `data/nq_agent_state/` directory
3. **Authorization**: Only responds to messages from your authorized chat ID
4. **Inline Buttons**: Status command includes interactive buttons for quick actions

## Security

- Commands are only processed from the authorized chat ID (TELEGRAM_CHAT_ID)
- Unauthorized access attempts are rejected
- All sensitive operations require proper authorization

## Troubleshooting

**Commands not working?**
1. Make sure command handler service is running
2. Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set correctly
3. Check that commands were set via BotFather
4. Verify your chat ID matches the authorized ID

**Handler won't start?**
1. Check that `python-telegram-bot` is installed: `pip install python-telegram-bot`
2. Verify environment variables are set in `.env` file
3. Check logs for error messages

## Future Enhancements

- Direct pause/resume control via commands (requires service integration)
- Real-time price queries
- Signal filtering and search
- Custom alerts and notifications
- Trade management commands

