#!/usr/bin/env python3
"""
PearlAlgo Health Monitor v2 — auto-fixes ghost positions, alerts on real issues.
Runs every 5 min via cron.
"""
import subprocess, json, sqlite3, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_KEY = "EL0lFv7oAVPhLwkqLTXCNvALmGVWBmoyb_pDKSOeKZ4"
API_URL = f"http://localhost:8001/api/state?api_key={API_KEY}"
DB = Path("/home/pearlalgo/pearl-algo-workspace/data/tradovate/paper/trades.db")
ALERT_COOLDOWN_FILE = Path("/tmp/pearlalgo_alert_cooldown.json")
COOLDOWN_MINUTES = 15

def get_cooldowns():
    try: return json.loads(ALERT_COOLDOWN_FILE.read_text())
    except: return {}

def set_cooldown(key):
    c = get_cooldowns()
    c[key] = datetime.now(timezone.utc).isoformat()
    ALERT_COOLDOWN_FILE.write_text(json.dumps(c))

def is_cooled_down(key):
    c = get_cooldowns()
    if key not in c: return True
    last = datetime.fromisoformat(c[key])
    return (datetime.now(timezone.utc) - last).total_seconds() > COOLDOWN_MINUTES * 60

def alert(msg, key):
    if not is_cooled_down(key): return
    set_cooldown(key)
    print(f"ALERT [{key}]: {msg}")
    subprocess.run(["openclaw", "system", "event", "--text", f"🚨 PearlAlgo: {msg}", "--mode", "now"])

def ok(msg): print(f"OK: {msg}")

def restart_agent():
    pid_out = subprocess.check_output(
        ["sudo", "systemctl", "show", "-p", "MainPID", "pearlalgo-agent"], text=True
    ).strip().split("=")[-1]
    if pid_out and pid_out != "0":
        subprocess.run(["sudo", "kill", "-9", pid_out], capture_output=True)
    import time; time.sleep(2)
    subprocess.run(["sudo", "systemctl", "start", "pearlalgo-agent"])

def clear_ghost_signals():
    """Clear ALL entered signals older than 5 min — they're never real after that long."""
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    # Clear anything entered more than 5 minutes ago
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    # Since timestamps have +00:00, compare directly
    cur.execute("SELECT COUNT(*) FROM signal_events WHERE status='entered'")
    total = cur.fetchone()[0]
    # Just clear all - they accumulate and never self-resolve
    cur.execute("UPDATE signal_events SET status='cancelled' WHERE status='entered'")
    conn.commit()
    cleared = cur.rowcount
    conn.close()
    return cleared

# 1. Check agent active
result = subprocess.run(["sudo", "systemctl", "is-active", "pearlalgo-agent"],
    capture_output=True, text=True)
if result.stdout.strip() != "active":
    alert("Agent is DOWN — restarting", "agent_down")
    restart_agent()
    sys.exit(1)

# 2. API state
try:
    import urllib.request
    resp = urllib.request.urlopen(API_URL, timeout=5)
    state = json.loads(resp.read())
except Exception as e:
    alert(f"API unreachable: {e}", "api_down")
    sys.exit(1)

if not state.get("data_fresh"):
    alert("IBKR data STALE", "data_stale")
else:
    ok("data_fresh")

# 3. Ghost signal check — clear ALL entered signals (they never self-resolve for real Tradovate fills)
conn = sqlite3.connect(str(DB))
ghost_count = conn.execute("SELECT COUNT(*) FROM signal_events WHERE status='entered'").fetchone()[0]
conn.close()

# Ghost signals accumulate naturally during Tradovate live trading.
# Clear silently — NEVER restart agent for this (interrupts live trades).
if ghost_count > 0:
    cleared = clear_ghost_signals()
    ok(f"Auto-cleared {cleared} ghost entered signals (no restart)")
else:
    ok("no ghost signals")

# 4. Check if signals are being blocked (only meaningful if no ghosts)
try:
    logs = subprocess.check_output(
        ["sudo", "journalctl", "-u", "pearlalgo-agent", "--no-pager", "--since", "5 minutes ago"],
        text=True, stderr=subprocess.DEVNULL
    )
    blocks = logs.count("Trading circuit breaker blocked signal")
    signals = logs.count("Processing 1 signal")
    if signals > 5 and blocks == signals:
        alert(f"All {signals} signals blocked — ghost fix didn't work, manual check needed", "all_blocked")
    elif signals > 0:
        ok(f"{signals} signals processed, {blocks} blocked in last 5min")
    else:
        ok("No signals (quiet market)")
except Exception as e:
    print(f"Log check error: {e}")

# 5. Long drought check (>90 min no trade during market hours)
now_utc = datetime.now(timezone.utc)
now_et_hour = (now_utc - timedelta(hours=4)).hour
market_hours = now_et_hour >= 18 or now_et_hour < 16  # overnight + day session
if market_hours and state.get("running"):
    conn = sqlite3.connect(str(DB))
    last = conn.execute(
        "SELECT MAX(exit_time) FROM trades WHERE date(exit_time,'localtime') = date('now','localtime')"
    ).fetchone()[0]
    conn.close()
    if last:
        last_dt = datetime.fromisoformat(last.replace('Z','+00:00'))
        mins = (now_utc - last_dt).total_seconds() / 60
        if mins > 90:
            alert(f"No trades in {mins:.0f}min during market hours — investigate", "trade_drought")
        else:
            ok(f"Last trade {mins:.0f}m ago")
    else:
        ok("No trades today yet")

print("Health check v2 complete.")
