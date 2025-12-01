# 🚀 Start the Agent RIGHT NOW - Step by Step

## Option 1: Simple Terminal Tab (Recommended for First Time)

### Step 1: Check IB Gateway
In your current terminal, run:
```bash
sudo systemctl status ibgateway.service
```

If it says "active (running)" - ✅ Good! Skip to Step 2.

If it says "inactive" - Start it:
```bash
sudo systemctl start ibgateway.service
sudo systemctl status ibgateway.service  # Verify it's running
```

### Step 2: Open New Terminal Tab
- Press `Ctrl+Shift+T` (new tab in same window)
- OR open a completely new terminal window

### Step 3: Navigate and Activate
In the NEW terminal tab, run:
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
```

### Step 4: Start the Agent
```bash
# Quick test - see it think (1-minute cycles)
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60
```

**That's it!** You'll see it start thinking and making decisions.

### To Stop
Press `Ctrl+C` in the terminal where it's running.

---

## Option 2: Using Screen (Detachable Session)

### What is Screen?
Screen lets you:
- Start the agent in a "session"
- Detach (close terminal, agent keeps running)
- Reattach later to see what happened

### Step 1: Check IB Gateway (same as above)
```bash
sudo systemctl status ibgateway.service
# Start if needed: sudo systemctl start ibgateway.service
```

### Step 2: Start Screen Session
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
screen -S trading
```

You'll see a new screen session start.

### Step 3: Run the Agent (inside screen)
```bash
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60
```

### Step 4: Detach from Screen
Press: `Ctrl+A` then `D` (press Ctrl+A, release, then press D)

You'll see: `[detached from 12345.trading]`

Now you can:
- Close the terminal
- The agent keeps running in the background
- Do other things

### Step 5: Reattach to Screen (later)
```bash
screen -r trading
```

You'll see exactly where you left off!

### To Stop the Agent (when attached)
1. Reattach: `screen -r trading`
2. Press `Ctrl+C` to stop the agent
3. Type `exit` to close the screen session

### Useful Screen Commands
```bash
screen -r trading          # Reattach
screen -ls                # List all screen sessions
screen -S trading -X quit # Kill session (if detached)
```

---

## Option 3: Using Tmux (Alternative to Screen)

### Step 1: Check IB Gateway
```bash
sudo systemctl status ibgateway.service
```

### Step 2: Start Tmux Session
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
tmux new -s trading
```

### Step 3: Run the Agent
```bash
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60
```

### Step 4: Detach from Tmux
Press: `Ctrl+B` then `D` (press Ctrl+B, release, then press D)

### Step 5: Reattach to Tmux
```bash
tmux attach -t trading
```

### To Stop
1. Reattach: `tmux attach -t trading`
2. Press `Ctrl+C` to stop
3. Type `exit` or press `Ctrl+D`

---

## Which Should You Use?

### Use Simple Terminal Tab If:
- ✅ First time running it
- ✅ Want to watch it in real-time
- ✅ Will be at your computer
- ✅ Easy to stop with Ctrl+C

### Use Screen/Tmux If:
- ✅ Want it to run in background
- ✅ Need to close terminal
- ✅ Want to check on it later
- ✅ Running for long periods

---

## Quick Reference

### Start Agent (Simple)
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60
```

### Start Agent (Screen - Detachable)
```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
screen -S trading
python scripts/automated_trading.py --symbols NQ --strategy sr --interval 60
# Detach: Ctrl+A then D
# Reattach: screen -r trading
```

### Check If Running
```bash
# If using screen
screen -ls

# If using simple terminal
ps aux | grep automated_trading
```

---

**Ready? Start with Option 1 (Simple Terminal Tab) to see it work!** 🎯

