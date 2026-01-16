## Pearl Algo Monitor (Linux) — Launch Guide

### Quick start (recommended)

Run this from the Beelink desktop session (local/VNC), not a headless SSH shell.

```bash
cd ~/pearlalgo-dev-ai-agents

# If you haven't installed monitor deps yet:
source .venv/bin/activate
pip install -e ".[monitor]"

# Start Gateway + Agent + Telegram + Monitor (GUI)
./scripts/lifecycle/start_monitor_suite.sh

# Start without Telegram (monitor + agent only)
./scripts/lifecycle/start_monitor_suite.sh --no-telegram
```

Stop everything:

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/lifecycle/stop_monitor_suite.sh
```

### Start only the monitor UI

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python -m pearlalgo.monitor
```

Or use the monitor launcher (foreground/background):

```bash
cd ~/pearlalgo-dev-ai-agents
./scripts/monitor/start_monitor.sh --background
./scripts/monitor/restart_monitor.sh
```

### Logs

- Monitor log: `logs/pearl_algo_monitor.log`
- Agent log (background mode): `logs/nq_agent.log`

```bash
tail -n 200 logs/pearl_algo_monitor.log
tail -n 200 logs/nq_agent.log
```

### Common issues

- **Nothing opens / crashes immediately**: open `logs/pearl_algo_monitor.log` and look for missing Qt/X11 libs.
- **Running from SSH**: GUI won’t open unless `DISPLAY`/Wayland is correctly set. Use `./scripts/monitor/start_monitor.sh --background` (auto-detects X11 displays) or force: `./scripts/monitor/start_monitor.sh --background --display=:0`.

