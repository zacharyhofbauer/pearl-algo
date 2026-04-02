#!/usr/bin/env python3
"""
PearlAlgo Health Monitor v2 — auto-fixes ghost positions, alerts on real issues.
Runs every 5 min via cron.
"""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = PROJECT_ROOT / "data" / "agent_state" / "MNQ"
STATE_DIR = Path(os.getenv("PEARLALGO_STATE_DIR", str(DEFAULT_STATE_DIR)))
DB = STATE_DIR / "trades.db"
API_URL = "http://localhost:8001/api/state"
ALERT_COOLDOWN_FILE = Path("/tmp/pearlalgo_alert_cooldown.json")
COOLDOWN_MINUTES = 15

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(Path.home() / ".config" / "pearlalgo" / "secrets.env", override=False)
except Exception:
    pass

API_KEY = os.getenv("PEARL_API_KEY", "").strip()

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

def table_exists(table_name):
    if not DB.exists():
        return False
    conn = sqlite3.connect(str(DB))
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()

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
    if not table_exists("signal_events"):
        return 0
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
    request = urllib.request.Request(API_URL)
    if API_KEY:
        request.add_header("X-API-Key", API_KEY)
    resp = urllib.request.urlopen(request, timeout=5)
    state = json.loads(resp.read())
except Exception as e:
    alert(f"API unreachable: {e}", "api_down")
    sys.exit(1)

if not state.get("data_fresh"):
    alert("IBKR data STALE", "data_stale")
else:
    ok("data_fresh")

# 3. Ghost signal check — clear ALL entered signals (they never self-resolve for real Tradovate fills)
ghost_count = 0
if table_exists("signal_events"):
    conn = sqlite3.connect(str(DB))
    ghost_count = conn.execute("SELECT COUNT(*) FROM signal_events WHERE status='entered'").fetchone()[0]
    conn.close()

if not table_exists("signal_events"):
    ok(f"ghost-signal check skipped (no signal_events table in {DB})")
elif ghost_count > 0:
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
import pytz as _pytz  # FIXED 2026-03-25: ET timezone migration
_ET_HCK = _pytz.timezone("America/New_York")
now_et = datetime.now(_ET_HCK)
now_et_hour = now_et.hour
market_hours = now_et_hour >= 18 or now_et_hour < 16  # overnight + day session
if market_hours and state.get("running"):
    if not table_exists("trades"):
        ok(f"trade-drought check skipped (no trades table in {DB})")
    else:
        conn = sqlite3.connect(str(DB))
        last = conn.execute(
            "SELECT MAX(exit_time) FROM trades WHERE date(exit_time) = date('now')"  # FIXED 2026-03-25: times are naive ET
        ).fetchone()[0]
        conn.close()
        if last:
            last_dt = datetime.fromisoformat(last)  # FIXED 2026-03-25: naive ET, no tz conversion needed
            mins = (now_et.replace(tzinfo=None) - last_dt).total_seconds() / 60
            if mins > 90:
                alert(f"No trades in {mins:.0f}min during market hours — investigate", "trade_drought")
            else:
                ok(f"Last trade {mins:.0f}m ago")
        else:
            ok("No trades today yet")

print("Health check v2 complete.")
