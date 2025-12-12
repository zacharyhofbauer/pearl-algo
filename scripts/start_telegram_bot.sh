#!/bin/bash
# Start Interactive Telegram Bot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
PID_FILE="$LOG_DIR/telegram_bot.pid"
LOG_FILE="$LOG_DIR/telegram_bot.log"

cd "$PROJECT_DIR"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "❌ Telegram Bot already running (PID: $PID)"
        echo "   Use 'pkill -f telegram_bot' to stop it first"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# Check for bot token
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN environment variable not set"
    exit 1
fi

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

echo "=== Starting Interactive Telegram Bot ==="
echo ""

# Start bot in background
nohup python3 -m pearlalgo.nq_agent.telegram_bot > "$LOG_FILE" 2>&1 &
BOT_PID=$!

# Save PID
echo $BOT_PID > "$PID_FILE"

echo "✅ Telegram Bot started"
echo "   PID: $BOT_PID"
echo "   Log: $LOG_FILE"
echo "   PID File: $PID_FILE"
echo ""
echo "Send /start to your bot to see available commands"
echo "To view logs: tail -f $LOG_FILE"
echo "To stop: pkill -f telegram_bot"

