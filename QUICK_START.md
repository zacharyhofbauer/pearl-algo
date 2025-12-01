# 🚀 Quick Start - Run the Agent

## Best Option: Separate Terminal Tab

**Yes, run it in a separate terminal tab!** This way you can:
- ✅ See all the detailed reasoning in real-time
- ✅ Watch the beautiful formatted output
- ✅ Monitor trades as they happen
- ✅ Stop it easily with Ctrl+C

## Step-by-Step

### 1. Open a New Terminal Tab/Window
- Press `Ctrl+Shift+T` (new tab) or open a new terminal window

### 2. Navigate and Activate Environment
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
```

### 3. Check IB Gateway is Running (in original terminal)
```bash
sudo systemctl status ibgateway.service
# If not running:
sudo systemctl start ibgateway.service
```

### 4. Run the Agent (in new terminal tab)
```bash
# Quick test - see it think quickly
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60

# Or full production run
python scripts/automated_trading.py --symbols ES NQ GC --strategy sr --interval 300
```

## Alternative: Use Screen/Tmux (For Long-Running)

If you want to detach and reattach later:

### Using Screen
```bash
# Start a screen session
screen -S trading

# Inside screen, run the agent
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 300

# Detach: Press Ctrl+A then D
# Reattach: screen -r trading
```

### Using Tmux
```bash
# Start a tmux session
tmux new -s trading

# Inside tmux, run the agent
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 300

# Detach: Press Ctrl+B then D
# Reattach: tmux attach -t trading
```

## What to Watch For

In the terminal, you'll see:
- 🔍 Analysis tables showing decision reasoning
- 📊 Indicator values and distances
- ✅ Trade executions
- 📤 Position exits
- 📈 Cycle summaries with P&L

## Stopping

Press `Ctrl+C` in the terminal where it's running. The agent will:
- Stop gracefully
- Show final summary
- Save all state

## Pro Tip

Keep **two terminals open**:
1. **Terminal 1**: Run the agent (watch it think)
2. **Terminal 2**: Monitor health checks or run other commands
   ```bash
   # In terminal 2, you can run:
   python scripts/health_check.py
   python scripts/status_dashboard.py
   tail -f logs/automated_trading.log  # if logging to file
   ```

---

**Ready? Open that new terminal tab and run it!** 🎯

