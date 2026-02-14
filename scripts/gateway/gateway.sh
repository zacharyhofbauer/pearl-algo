#!/bin/bash
# ============================================================================
# Category: Gateway
# Purpose: Consolidated entry point for IBKR Gateway lifecycle + diagnostics
# Usage:
#   ./scripts/gateway/gateway.sh <command> [args...]
#
# Commands:
#   start               Start Gateway headless via IBC (Xvfb DISPLAY=:99)
#   start-vnc           Start Gateway via IBC on VNC display (:1) for manual interaction
#   stop                Stop Gateway (IBC)
#   status              Check Gateway status
#   api-ready           Check API port readiness (exit 0 if ready)
#   monitor             Monitor until API is ready (max 5 minutes)
#   tws-conflict         Detect TWS/Gateway conflicts and Error 162 hints
#   test-api            Attempt short API connect using ib_insync
#   2fa-status          Check whether 2FA is required (log-based)
#   wait-2fa            Wait for 2FA approval (mobile; max 10 minutes)
#   complete-2fa        Start VNC (if needed) and print 2FA entry instructions
#   auto-2fa [CODE]     Attempt to auto-enter 2FA code (requires xdotool)
#   setup [mode] [ibc]  One-time gateway + IBC setup (mode=readonly/full, ibc=yes/no)
#   vnc-setup           One-time VNC setup for manual login
#   vnc-config-api      One-time API config guidance via VNC
#   disable-sleep       Disable auto-sleep (host helper)
#
# Notes:
# - This script is the canonical gateway CLI; legacy per-purpose scripts were consolidated.
# - No trading logic lives here.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load a single env var from .env (best-effort; avoids executing .env).
_maybe_load_dotenv_var() {
  local key="$1"
  local env_file="$PROJECT_DIR/.env"

  # If already set in the shell, do not override.
  if [ -n "${!key-}" ]; then
    return 0
  fi

  if [ ! -f "$env_file" ]; then
    return 0
  fi

  local line=""
  while IFS= read -r line || [ -n "$line" ]; do
    # Strip comments + surrounding whitespace.
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"   # ltrim
    line="${line%"${line##*[![:space:]]}"}"   # rtrim
    [ -z "$line" ] && continue

    if [[ "$line" == "$key="* ]]; then
      local value="${line#*=}"
      value="${value%\"}"; value="${value#\"}"
      value="${value%\'}"; value="${value#\'}"
      export "${key}=${value}"
      return 0
    fi
  done < "$env_file"
}

# Allow .env to set the external IBKR home (recommended).
_maybe_load_dotenv_var "PEARLALGO_IBKR_HOME"
# Optional: allow .env to provide IBC login/config inputs (best-effort).
_maybe_load_dotenv_var "IBKR_USERNAME"
_maybe_load_dotenv_var "IBKR_PASSWORD"
_maybe_load_dotenv_var "IBKR_ACCOUNT_TYPE"
_maybe_load_dotenv_var "IBKR_READ_ONLY_API"
_maybe_load_dotenv_var "IBKR_PORT"

IBKR_HOME_DEFAULT="$PROJECT_DIR/ibkr"
IBKR_HOME="${PEARLALGO_IBKR_HOME:-$IBKR_HOME_DEFAULT}"
IBC_DIR=""
IBC_LOG_DIR=""
JTS_DIR=""
API_PORT="${IBKR_PORT:-4002}"


_set_ibkr_paths() {
  IBC_DIR="$IBKR_HOME/ibc"
  IBC_LOG_DIR="$IBKR_HOME/ibc/logs"
  JTS_DIR="$IBKR_HOME/Jts"
}


_require_ibkr_home() {
  if [ ! -d "$IBKR_HOME" ]; then
    echo "❌ IBKR home not found: $IBKR_HOME"
    echo "   Set PEARLALGO_IBKR_HOME or pass --ibkr-home."
    echo "   Example: PEARLALGO_IBKR_HOME=/opt/ibkr ./scripts/gateway/gateway.sh status"
    exit 1
  fi
}


_set_ibkr_paths


_ensure_ibkr_install() {
  _require_ibkr_home

  if [ ! -d "$IBC_DIR" ] || [ ! -f "$IBC_DIR/gatewaystart.sh" ]; then
    echo "❌ IBC install not found under: $IBC_DIR"
    echo "   Expected gatewaystart.sh in $IBC_DIR"
    echo "   Run: ./scripts/gateway/gateway.sh install-info"
    exit 1
  fi
}


_pick_python() {
  # Prefer the project venv when present so dependencies (ib_insync) resolve.
  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    echo "$PROJECT_DIR/.venv/bin/python"
  elif [ -x "$PROJECT_DIR/.venv/bin/python3" ]; then
    echo "$PROJECT_DIR/.venv/bin/python3"
  else
    echo "python3"
  fi
}


_gateway_pid() {
  pgrep -f "java.*IBC.jar" 2>/dev/null | head -1 || true
}


_gateway_running() {
  pgrep -f "java.*IBC.jar" >/dev/null 2>&1
}


_api_listening() {
  ss -tuln 2>/dev/null | grep -q ":${API_PORT}"
}


_ensure_xvfb() {
  if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
    sleep 2
  fi
  export DISPLAY=:99
}


_ensure_vnc() {
  # Ensure a VNC display :1 is available. We accept either Xtigervnc or Xvnc patterns.
  if ! pgrep -f "Xtigervnc.*:1" >/dev/null 2>&1 && ! pgrep -f "Xvnc.*:1" >/dev/null 2>&1; then
    echo "⚠️  VNC server may not be running on :1"
    echo "   Starting VNC server..."
    vncserver :1 -geometry 1024x768 -depth 24 2>&1 | head -5
    sleep 2
  fi
  export DISPLAY=:1
}

_patch_ibc_start_script() {
  # Patch IBC start scripts (gatewaystart.sh / twsstart.sh) to match our install paths.
  # These scripts are designed to be edited; we keep this targeted + idempotent.
  local file="$1"
  local tws_major="$2"
  local ibc_ini="$3"
  local ibc_path="$4"
  local tws_path="$5"
  local log_path="$6"

  python3 - "$file" "$tws_major" "$ibc_ini" "$ibc_path" "$tws_path" "$log_path" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
tws_major = sys.argv[2]
ibc_ini = sys.argv[3]
ibc_path = sys.argv[4]
tws_path = sys.argv[5]
log_path = sys.argv[6]

text = path.read_text(encoding="utf-8", errors="ignore")

replacements = {
    "TWS_MAJOR_VRSN": tws_major,
    "IBC_INI": ibc_ini,
    "IBC_PATH": ibc_path,
    "TWS_PATH": tws_path,
    "LOG_PATH": log_path,
}

for key, value in replacements.items():
    pattern = re.compile(rf"^{re.escape(key)}=.*$", flags=re.M)
    if pattern.search(text):
        text = pattern.sub(f"{key}={value}", text, count=1)

path.write_text(text, encoding="utf-8")
PY
}

_patch_ibcstart_for_standalone_layout() {
  # Newer IB Gateway standalone installers place `jars/` directly under TWS_PATH (eg, ~/Jts/jars),
  # while IBC expects the "offline" layout (eg, ~/Jts/ibgateway/1037/jars). Patch IBC's script
  # to accept either layout. Idempotent via marker.
  local file="$1"
  if [ ! -f "$file" ]; then
    return 0
  fi
  if grep -q "standalone installs where jars live directly under tws_path" "$file" 2>/dev/null; then
    return 0
  fi

  python3 - "$file" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="ignore")

marker = "standalone installs where jars live directly under tws_path"
if marker in text:
    sys.exit(0)

needle = '\t\ttws_program_path="${tws_path}/${tws_version}"\n\t\tgateway_program_path="${tws_path}/ibgateway/${tws_version}"'
if needle not in text:
    sys.exit(0)

injected = (
    needle
    + '\n\t\t# Support newer standalone installs where jars live directly under tws_path'
    + '\n\t\t# (instead of under ${tws_path}/ibgateway/${tws_version}).'
    + '\n\t\tif [[ -d "${tws_path}/jars" ]]; then'
    + '\n\t\t\ttws_program_path="${tws_path}"'
    + '\n\t\t\tgateway_program_path="${tws_path}"'
    + '\n\t\tfi'
)

path.write_text(text.replace(needle, injected), encoding="utf-8")
PY
}


cmd_start() {
  cd "$PROJECT_DIR"
  echo "=== Starting IB Gateway with IBC (Read-Only Mode) ==="
  echo ""
  _ensure_ibkr_install

  if _gateway_running; then
    echo "⚠️  IB Gateway is already running!"
    ps aux | grep "IBC.jar" | grep -v grep
    echo ""
    if _api_listening; then
      echo "   API is ready — treating as success (e.g. after restart)."
      exit 0
    fi
    echo "To stop it: ./scripts/gateway/gateway.sh stop"
    exit 1
  fi

  if [ ! -f "$IBC_DIR/config-auto.ini" ]; then
    echo "❌ IBC not configured."
    echo "   Run: ./scripts/gateway/gateway.sh setup"
    exit 1
  fi

  _ensure_xvfb

  echo "Starting IB Gateway..."
  cd "$IBC_DIR"

  # Ensure log directory exists (IBC zip doesn't always include it).
  mkdir -p "$IBC_LOG_DIR"

  LOG_FILE="logs/gateway_$(date +%Y%m%d_%H%M%S).log"
  nohup ./gatewaystart.sh -inline > "$LOG_FILE" 2>&1 &
  IBC_PID=$!

  echo "IB Gateway starting (PID: $IBC_PID)"
  echo "Log file: $IBC_DIR/$LOG_FILE"
  echo ""

  echo "Waiting for Gateway to start and authenticate..."
  sleep 10

  if ! ps -p "$IBC_PID" >/dev/null 2>&1; then
    echo "⚠️  Process exited - checking logs..."
    tail -30 "$LOG_FILE" 2>/dev/null | tail -15 || true
    echo ""
    echo "Check full log: tail -f $IBC_DIR/$LOG_FILE"
    exit 1
  fi

  echo "✅ IB Gateway process is running"

  echo "Waiting for authentication and API to become available..."
  for i in {1..12}; do
    sleep 5
    if _api_listening; then
      echo "✅ API port ${API_PORT} is listening!"
      echo ""
      echo "=== IB Gateway is ready for data access ==="
      echo ""
      echo "Gateway is running and authenticated."
      echo "It will stay running until you stop it."
      echo ""
      echo "To stop Gateway: ./scripts/gateway/gateway.sh stop"
      echo "To view logs: tail -f $IBC_DIR/$LOG_FILE"
      echo ""
      echo "Test API handshake:"
      echo "  ./scripts/gateway/gateway.sh test-api"
      exit 0
    fi
    echo "  Still waiting... ($i/12)"
  done

  echo "⚠️  Port ${API_PORT} not listening after 60 seconds"
  echo ""
  echo "📱 If you're using IBKR mobile app for 2FA:"
  echo "   1. Check your mobile app for a login approval notification"
  echo "   2. Tap 'Approve' or 'Allow' to approve the login"
  echo "   3. Gateway will automatically continue after approval"
  echo ""
  echo "   To monitor authentication progress:"
  echo "   ./scripts/gateway/gateway.sh wait-2fa"
  echo ""
  echo "Check status:"
  echo "  ./scripts/gateway/gateway.sh status"
  echo ""
  echo "View logs:"
  echo "  tail -f $IBC_DIR/$LOG_FILE"
  echo "  tail -f $IBC_DIR/logs/ibc-*.txt"
  echo ""
  echo "To stop IB Gateway: ./scripts/gateway/gateway.sh stop"
  exit 1
}


cmd_start_vnc() {
  cd "$PROJECT_DIR"
  echo "=== Starting IB Gateway with IBC on VNC Display ==="
  echo ""
  _ensure_ibkr_install

  _ensure_vnc
  echo "✅ VNC server is running on :1"
  echo ""

  if _gateway_running; then
    echo "⚠️  IB Gateway is already running!"
    ps aux | grep "IBC.jar" | grep -v grep
    echo ""
    if _api_listening; then
      echo "   API is ready — treating as success."
      exit 0
    fi
    echo "To stop it: ./scripts/gateway/gateway.sh stop"
    exit 1
  fi

  if [ ! -f "$IBC_DIR/config-auto.ini" ]; then
    echo "❌ IBC not configured."
    echo "   Run: ./scripts/gateway/gateway.sh setup"
    exit 1
  fi

  echo "Starting IB Gateway on VNC display :1..."
  cd "$IBC_DIR"
  export DISPLAY=:1

  # Ensure log directory exists (IBC zip doesn't always include it).
  mkdir -p "$IBC_LOG_DIR"

  LOG_FILE="logs/gateway_$(date +%Y%m%d_%H%M%S).log"
  nohup ./gatewaystart.sh -inline > "$LOG_FILE" 2>&1 &
  IBC_PID=$!

  echo "IB Gateway starting on VNC display :1 (PID: $IBC_PID)"
  echo "Log file: $IBC_DIR/$LOG_FILE"
  echo ""
  echo "✅ Gateway should now be visible in your VNC viewer!"
  echo ""
  SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"
  echo "Connect to VNC:"
  echo "  vncviewer ${SERVER_IP}:5901"
  echo "  (or use SSH tunnel: ssh -L 5901:localhost:5901 <user>@${SERVER_IP})"
  echo ""
  echo "Check API status:"
  echo "  ./scripts/gateway/gateway.sh api-ready"
}


cmd_stop() {
  cd "$PROJECT_DIR"
  echo "=== Stopping IB Gateway ==="
  echo ""
  _ensure_ibkr_install

  GATEWAY_PID="$(_gateway_pid)"
  if [ -z "$GATEWAY_PID" ]; then
    echo "❌ IB Gateway is not running"
    exit 1
  fi

  echo "Found Gateway process: $GATEWAY_PID"
  echo "Stopping Gateway..."

  if [ -f "$IBC_DIR/stop.sh" ]; then
    echo "Using IBC stop script..."
    cd "$IBC_DIR"
    ./stop.sh 2>/dev/null || true
    sleep 3
  else
    echo "IBC stop script not found, killing process directly..."
    kill "$GATEWAY_PID" 2>/dev/null || true
    sleep 2
  fi

  if _gateway_running; then
    echo "⚠️  Process didn't stop gracefully, force killing..."
    pkill -9 -f "java.*IBC.jar" || true
    sleep 2
  fi

  if _gateway_running; then
    echo "   Retrying force kill..."
    pkill -9 -f "java.*IBC.jar" || true
    sleep 1
  fi

  if _gateway_running; then
    echo "❌ Failed to stop Gateway"
    exit 1
  fi

  echo "✅ IB Gateway stopped"
}


cmd_status() {
  cd "$PROJECT_DIR"
  echo "=== IBKR Gateway Status ==="
  echo ""
  _ensure_ibkr_install

  if _gateway_running; then
    echo "✅ Gateway Process: RUNNING"
    ps aux | grep "IBC.jar" | grep -v grep | awk '{print "   PID: " $2 ", Started: " $9}'
  else
    echo "❌ Gateway Process: NOT RUNNING"
  fi

  echo ""

  if _api_listening; then
    echo "✅ API Port ${API_PORT}: LISTENING"
    ss -tuln | grep ":${API_PORT}" | awk '{print "   " $0}'
  else
    echo "❌ API Port ${API_PORT}: NOT LISTENING"
  fi

  echo ""

  LATEST_LOG="$(ls -t "$IBC_LOG_DIR"/gateway_*.log 2>/dev/null | head -1 || true)"
  if [ -n "$LATEST_LOG" ]; then
    echo "📄 Latest Log: $LATEST_LOG"
    echo "   Last modified: $(stat -c %y "$LATEST_LOG" 2>/dev/null | cut -d. -f1)"
  else
    echo "📄 Latest Log: Not found"
  fi

  echo ""

  if _gateway_running && _api_listening; then
    echo "🎉 Gateway is RUNNING and READY for data access!"
  elif _gateway_running; then
    echo "⚠️  Gateway is running but API not ready yet (may still be authenticating)"
  else
    echo "❌ Gateway is not running. Start it with: ./scripts/gateway/gateway.sh start"
  fi
}


cmd_api_ready() {
  cd "$PROJECT_DIR"
  echo "Checking Gateway API status..."
  echo ""
  _ensure_ibkr_install

  if ! _gateway_running; then
    echo "❌ Gateway is not running"
    exit 1
  fi

  GATEWAY_PID="$(_gateway_pid)"
  echo "✅ Gateway is running (PID: $GATEWAY_PID)"
  echo ""

  if _api_listening; then
    echo "✅✅✅ API port ${API_PORT} is LISTENING!"
    echo ""
    echo "Gateway is ready for connections!"
    echo ""
    echo "You can now start the Market Agent service:"
    echo "   ./scripts/lifecycle/agent.sh start --market NQ --background"
    exit 0
  fi

  echo "⏳ API port ${API_PORT} is not yet listening"
  echo ""
  echo "Gateway is still authenticating or starting up..."
  echo ""
  echo "If you approved the login in your mobile app, wait 30-60 seconds"
  echo "and run this command again:"
  echo "   ./scripts/gateway/gateway.sh api-ready"
  echo ""
  echo "Or monitor continuously:"
  echo "   ./scripts/gateway/gateway.sh monitor"
  exit 1
}


cmd_monitor() {
  cd "$PROJECT_DIR"
  echo "=== Monitoring Gateway until API is ready ==="
  echo ""
  _ensure_ibkr_install

  MAX_WAIT=300
  CHECK_INTERVAL=5
  ELAPSED=0

  while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    if _api_listening; then
      echo ""
      echo "✅✅✅ SUCCESS! API port ${API_PORT} is listening!"
      echo ""
      echo "Gateway is ready for connections!"
      echo ""
      echo "You can now start the Market Agent service:"
      echo "   ./scripts/lifecycle/agent.sh start --market NQ --background"
      exit 0
    fi

    if [ $((ELAPSED % 15)) -eq 0 ] && [ "$ELAPSED" -gt 0 ]; then
      echo "   Still waiting... (${ELAPSED}s elapsed)"
      if ! _gateway_running; then
        echo "   ⚠️  Gateway process not running!"
        exit 1
      fi
    fi

    sleep "$CHECK_INTERVAL"
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
  done

  echo ""
  echo "⏱️  Timeout after ${MAX_WAIT} seconds"
  echo "   Check Gateway status: ./scripts/gateway/gateway.sh tws-conflict"
  exit 1
}


cmd_tws_conflict() {
  cd "$PROJECT_DIR"
  echo "=== IBKR Connection Conflict Check ==="
  echo ""

  GATEWAY_PID="$(pgrep -f "java.*IBC.jar" 2>/dev/null || true)"
  if [ -n "$GATEWAY_PID" ]; then
    echo "✅ IBKR Gateway: RUNNING (PID: $GATEWAY_PID)"
  else
    echo "❌ IBKR Gateway: NOT RUNNING"
  fi

  echo ""

  TWS_PIDS="$(pgrep -f "tws|Trader Workstation" 2>/dev/null | while read -r pid; do
    cmd=$(ps -p "$pid" -o cmd --no-headers 2>/dev/null || true)
    if [ -n "$GATEWAY_PID" ] && [ "$pid" = "$GATEWAY_PID" ]; then
      continue
    fi
    if echo "$cmd" | grep -qE "(ibcstart|gatewaystart|IBC\.jar|IbcGateway)"; then
      continue
    fi
    if echo "$cmd" | grep -q "gateway.sh"; then
      continue
    fi
    echo "$pid"
  done)"

  if [ -n "$TWS_PIDS" ]; then
    echo "⚠️  WARNING: TWS (Trader Workstation) processes detected:"
    for PID in $TWS_PIDS; do
      ps -p "$PID" -o pid,cmd --no-headers 2>/dev/null | awk '{print "   PID " $1 ": " substr($0, index($0,$2))}'
    done
    echo ""
    echo "💡 If TWS is connected from a different IP, you'll get Error 162."
    echo "   Solution: Close TWS or disconnect it, then restart Gateway."
  else
    echo "✅ No TWS processes detected (Gateway-only mode)"
  fi

  echo ""

  if [ -f "logs/agent_NQ.log" ]; then
    ERROR_162_COUNT="$(grep -c "Error 162\|TWS session\|different IP" logs/agent_NQ.log 2>/dev/null || echo "0")"
    ERROR_162_COUNT="$(echo "$ERROR_162_COUNT" | tr -d '\n' | head -1)"
    if [ -n "$ERROR_162_COUNT" ] && [ "$ERROR_162_COUNT" -gt 0 ] 2>/dev/null; then
      echo "⚠️  Error 162 detected in logs ($ERROR_162_COUNT occurrences)"
      echo "   Recent occurrences:"
      grep "Error 162\|TWS session\|different IP" logs/agent_NQ.log | tail -3 | sed 's/^/   /'
      echo ""
      echo "💡 This indicates a TWS/Gateway IP conflict."
    else
      echo "✅ No Error 162 in recent logs"
    fi
  fi
}


cmd_test_api() {
  cd "$PROJECT_DIR"
  echo "=== Testing API Connection ==="
  echo ""
  _ensure_ibkr_install

  if ! _gateway_running; then
    echo "❌ Gateway is not running"
    exit 1
  fi

  echo "✅ Gateway is running"
  echo ""
  echo "Attempting API connection to trigger any pending dialogs..."
  echo ""

  PY="$(_pick_python)"
  API_PORT="$API_PORT" "$PY" << 'EOF'
import os
import sys

try:
    from ib_insync import IB
except ModuleNotFoundError:
    print("❌ ib_insync is not installed in this Python environment.")
    print(f"   Python: {sys.executable}")
    print("   Fix: install project deps (e.g. `pip install -e .`).")
    raise SystemExit(2)

ib = IB()
port = int(os.environ.get("API_PORT", "4002"))
try:
    print(f"Python: {sys.executable}")
    print(f"Connecting to Gateway at 127.0.0.1:{port}...")
    ib.connect("127.0.0.1", port, clientId=99, timeout=10)
    if ib.isConnected():
        print("✅✅✅ SUCCESS! API connection established!")
        print("   Gateway is ready for connections")
        ib.disconnect()
        raise SystemExit(0)
    print("❌ Connection failed")
    raise SystemExit(1)
except Exception as e:
    err = str(e).lower()
    if "connection refused" in err or "111" in str(e):
        print("⏳ API port not yet listening")
        print("   Gateway may still be starting up")
        print("   Or there may be a dialog waiting for approval")
    elif "write access" in err or "permission" in err:
        print("⚠️  Write access dialog may be blocking connection")
        print("   Check Gateway logs for 'API client needs write access' dialog")
    else:
        print(f"❌ Connection error: {e}")
    raise SystemExit(1)
EOF
}


cmd_2fa_status() {
  cd "$PROJECT_DIR"
  echo "=== IBKR Gateway 2FA Status Check ==="
  echo ""
  _ensure_ibkr_install

  if _gateway_running; then
    GATEWAY_PID="$(_gateway_pid)"
    echo "✅ Gateway is running (PID: $GATEWAY_PID)"
  else
    echo "❌ Gateway is NOT running"
    echo "   Start it: ./scripts/gateway/gateway.sh start"
    exit 1
  fi

  if _api_listening; then
    echo "✅ API port ${API_PORT} is LISTENING - Gateway is ready!"
    echo ""
    echo "You can now start the Market Agent service:"
    echo "   ./scripts/lifecycle/agent.sh start --market NQ --background"
    exit 0
  fi

  echo "⚠️  API port ${API_PORT} is NOT listening yet"
  echo ""

  LATEST_LOG="$(ls -t "$IBC_LOG_DIR"/ibc-*.txt 2>/dev/null | head -1 || true)"
  if [ -n "$LATEST_LOG" ]; then
    echo "📋 Recent Gateway activity:"
    echo ""
    tail -20 "$LATEST_LOG" | grep -E "2FA|Second Factor|Authentication|Authenticated|Logged|main window|API" | tail -5 || true
    echo ""

    if grep -q "Second Factor Authentication" "$LATEST_LOG" && ! grep -q "Authenticated\|Logged.*in" "$LATEST_LOG"; then
      echo "🔐 Gateway is WAITING for 2FA authentication"
      echo ""
      echo "To complete 2FA:"
      echo "  ./scripts/gateway/gateway.sh complete-2fa"
    elif grep -q "Authenticated\|Logged.*in\|main window" "$LATEST_LOG"; then
      echo "✅ Gateway appears to be authenticated"
      echo "   Waiting for API port to become available..."
    fi
  else
    echo "⚠️  Could not find Gateway logs"
  fi

  echo ""
  echo "=== Quick Commands ==="
  echo "Check API port: ss -tuln | grep ${API_PORT}"
  echo "View Gateway logs: tail -f $IBC_LOG_DIR/ibc-*.txt"
  echo "Check Gateway process: ps aux | grep IBC.jar"
}


cmd_wait_2fa() {
  cd "$PROJECT_DIR"
  echo "=== Waiting for IBKR Mobile App 2FA Approval ==="
  echo ""
  _ensure_ibkr_install

  if ! _gateway_running; then
    echo "❌ IB Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/gateway.sh start"
    exit 1
  fi

  GATEWAY_PID="$(_gateway_pid)"
  echo "✅ Gateway is running (PID: $GATEWAY_PID)"
  echo ""

  LATEST_LOG="$(ls -t "$IBC_LOG_DIR"/ibc-*.txt 2>/dev/null | head -1 || true)"
  if [ -z "$LATEST_LOG" ]; then
    echo "⚠️  Could not find IBC log file"
  else
    echo "📋 Monitoring log: $LATEST_LOG"
  fi

  echo ""
  echo "📱 ACTION REQUIRED:"
  echo "   1. Check your IBKR mobile app"
  echo "   2. You should see a login approval notification"
  echo "   3. Tap 'Approve' or 'Allow' to approve the login"
  echo ""
  echo "⏳ Waiting for authentication to complete..."
  echo ""

  MAX_WAIT=600
  CHECK_INTERVAL=2
  ELAPSED=0

  while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    if _api_listening; then
      echo ""
      echo "✅✅✅ SUCCESS! Gateway is authenticated and API is ready!"
      echo ""
      echo "You can now start the Market Agent service:"
      echo "   ./scripts/lifecycle/agent.sh start --market NQ --background"
      exit 0
    fi

    if [ -n "${LATEST_LOG:-}" ] && [ -f "${LATEST_LOG:-}" ]; then
      if grep -qi "logged in\|authenticated\|main window" "$LATEST_LOG" 2>/dev/null; then
        echo "   ℹ️  Log shows authentication may have completed..."
      fi
    fi

    if ! ps -p "$GATEWAY_PID" >/dev/null 2>&1; then
      echo ""
      echo "❌ Gateway process exited!"
      if [ -n "${LATEST_LOG:-}" ]; then
        echo "   Check logs: tail -50 $LATEST_LOG"
      fi
      exit 1
    fi

    if [ $((ELAPSED % 10)) -eq 0 ] && [ "$ELAPSED" -gt 0 ]; then
      echo "   Still waiting... (${ELAPSED}s elapsed)"
      echo "   📱 Remember to approve the login in your IBKR mobile app!"
    fi

    sleep "$CHECK_INTERVAL"
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
  done

  echo ""
  echo "⏱️  Timeout after ${MAX_WAIT} seconds"
  echo ""
  echo "📋 Troubleshooting:"
  echo "   1. Did you approve the login in your IBKR mobile app?"
  echo "   2. Check Gateway status: ./scripts/gateway/gateway.sh tws-conflict"
  if [ -n "${LATEST_LOG:-}" ]; then
    echo "   3. Check logs: tail -50 $LATEST_LOG"
  fi
  echo "   4. Check if API port is ready: ss -tuln | grep ${API_PORT}"
  exit 1
}


cmd_complete_2fa() {
  cd "$PROJECT_DIR"
  echo "=== Complete 2FA Authentication for IBKR Gateway ==="
  echo ""
  _ensure_ibkr_install

  if ! _gateway_running; then
    echo "❌ IB Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/gateway.sh start"
    exit 1
  fi

  echo "✅ Gateway is running and may be waiting for 2FA"
  echo ""

  VNC_DISPLAY=":1"
  if pgrep -f "Xvnc.*${VNC_DISPLAY}" >/dev/null 2>&1; then
    echo "✅ VNC server already running on ${VNC_DISPLAY}"
  else
    echo "Starting VNC server on ${VNC_DISPLAY}..."
    vncserver ${VNC_DISPLAY} -geometry 1024x768 -depth 24 2>&1 | tee /tmp/vnc_start.log >/dev/null
  fi

  SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"

  echo ""
  echo "=== Connect to VNC ==="
  echo ""
  echo "Option 1: Direct connection:"
  echo "   vncviewer ${SERVER_IP}:5901"
  echo ""
  echo "Option 2: SSH tunnel (recommended):"
  echo "   ssh -L 5901:localhost:5901 ${USER}@${SERVER_IP}"
  echo "   Then: vncviewer localhost:5901"
  echo ""
  echo "=== In VNC Session ==="
  echo ""
  echo "1. Look for the 'Second Factor Authentication' dialog"
  echo "2. Enter your 2FA code from your authenticator app"
  echo "3. Click 'OK' or 'Submit'"
  echo ""
  echo "After authentication:"
  echo "  ./scripts/gateway/gateway.sh api-ready"
}


cmd_auto_2fa() {
  # Directly inlined from the legacy script; kept as a utility.
  twofa_arg="${1:-}"

  echo "=== Auto 2FA Entry for IBKR Gateway ==="
  echo ""
  _ensure_ibkr_install

  if ! _gateway_running; then
    echo "❌ IB Gateway is not running!"
    exit 1
  fi

  echo "✅ Gateway is running"
  echo ""

  TWOFA_FILE="$HOME/.ibkr_2fa_code"
  TWOFA_TIMEOUT=300

  echo "Waiting for 2FA code..."
  echo ""
  echo "Option 1: Write 2FA code to file:"
  echo "   echo 'YOUR_2FA_CODE' > $TWOFA_FILE"
  echo ""
  echo "Option 2: Set environment variable:"
  echo "   export IBKR_2FA_CODE='YOUR_2FA_CODE'"
  echo "   ./scripts/gateway/gateway.sh auto-2fa"
  echo ""
  echo "Option 3: Pass as argument:"
  echo "   ./scripts/gateway/gateway.sh auto-2fa YOUR_2FA_CODE"
  echo ""

  TWOFA_CODE=""
  if [ -n "$twofa_arg" ]; then
    TWOFA_CODE="$twofa_arg"
    echo "✅ 2FA code provided as argument"
  elif [ -n "${IBKR_2FA_CODE:-}" ]; then
    TWOFA_CODE="$IBKR_2FA_CODE"
    echo "✅ 2FA code found in environment variable"
  elif [ -f "$TWOFA_FILE" ]; then
    FILE_AGE=$(($(date +%s) - $(stat -c %Y "$TWOFA_FILE" 2>/dev/null || echo 0)))
    if [ "$FILE_AGE" -lt 60 ]; then
      TWOFA_CODE="$(cat "$TWOFA_FILE" | tr -d '\n\r ' | head -c 10)"
      echo "✅ 2FA code read from file (age: ${FILE_AGE}s)"
      rm -f "$TWOFA_FILE"
    else
      echo "⚠️  2FA file too old (${FILE_AGE}s), waiting for new code..."
    fi
  fi

  if [ -z "$TWOFA_CODE" ]; then
    echo ""
    echo "⏳ Waiting for 2FA code (timeout: ${TWOFA_TIMEOUT}s)..."
    echo "   Write code to: $TWOFA_FILE"
    echo ""
    START_TIME=$(date +%s)
    while [ $(($(date +%s) - $START_TIME)) -lt $TWOFA_TIMEOUT ]; do
      if [ -f "$TWOFA_FILE" ]; then
        FILE_AGE=$(($(date +%s) - $(stat -c %Y "$TWOFA_FILE" 2>/dev/null || echo 0)))
        if [ "$FILE_AGE" -lt 60 ]; then
          TWOFA_CODE="$(cat "$TWOFA_FILE" | tr -d '\n\r ' | head -c 10)"
          echo "✅ Got 2FA code from file!"
          rm -f "$TWOFA_FILE"
          break
        fi
      fi
      sleep 1
    done
  fi

  if [ -z "$TWOFA_CODE" ]; then
    echo "❌ No 2FA code received within timeout"
    exit 1
  fi

  echo ""
  echo "🔑 2FA Code: ${TWOFA_CODE:0:2}****"
  echo ""

  if ! command -v xdotool >/dev/null 2>&1; then
    echo "⚠️  xdotool not installed - cannot automate GUI"
    echo ""
    echo "To install xdotool:"
    echo "   sudo apt-get install xdotool"
    echo ""
    echo "Or manually enter the code in the Gateway window."
    exit 1
  fi

  echo "✅ Using xdotool for GUI automation"
  echo "   Searching for 2FA dialog..."

  for DISPLAY_NUM in ":99" ":1" ""; do
    if [ -n "$DISPLAY_NUM" ]; then
      export DISPLAY="$DISPLAY_NUM"
    fi

    DIALOG_WIN=""
    for _i in {1..30}; do
      DIALOG_WIN="$(xdotool search --name "Second Factor Authentication" 2>/dev/null | head -1 || true)"
      if [ -n "$DIALOG_WIN" ]; then
        echo "   ✅ Found 2FA dialog (window: $DIALOG_WIN)"
        break
      fi
      sleep 1
    done

    if [ -n "$DIALOG_WIN" ]; then
      xdotool windowactivate "$DIALOG_WIN" 2>/dev/null || true
      sleep 0.5
      echo "   Entering 2FA code..."
      xdotool type --clearmodifiers "$TWOFA_CODE" 2>/dev/null || true
      sleep 0.5
      xdotool click 1 2>/dev/null || true
      sleep 0.2
      xdotool type --clearmodifiers "$TWOFA_CODE" 2>/dev/null || true
      sleep 0.5
      echo "   Submitting..."
      xdotool key Return 2>/dev/null || true
      sleep 0.5
      echo "   ✅ 2FA code entered and submitted!"
      echo ""
      echo "   Waiting 30 seconds for Gateway to authenticate..."
      sleep 30
      if _api_listening; then
        echo "   ✅ API port ${API_PORT} is listening - Gateway authenticated!"
        exit 0
      fi
      echo "   ⚠️  API port not yet ready, but code was entered"
      exit 0
    fi
  done

  echo "   ⚠️  Could not find 2FA dialog window"
  exit 1
}


cmd_vnc_setup() {
  echo "=== VNC Setup for IBKR Gateway Manual Login ==="
  echo ""

  if pgrep -f "Xvnc.*:1" >/dev/null 2>&1; then
    echo "⚠️  VNC server already running on :1"
    echo "   To kill it: vncserver -kill :1"
    echo ""
    SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"
    echo "✅ Connect via VNC:"
    echo "   vncviewer $SERVER_IP:5901"
    exit 0
  fi

  echo "Starting VNC server on display :1..."
  vncserver :1 -geometry 1024x768 -depth 24

  SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"
  echo ""
  echo "=== Connection Instructions ==="
  echo "1. Connect via VNC: vncviewer $SERVER_IP:5901"
  echo "2. In VNC, start Gateway:"
  echo "   cd $IBC_DIR"
  echo "   export DISPLAY=:1"
  echo "   ./gatewaystart.sh"
  echo "3. Complete login + 2FA"
  echo "4. After login, stop VNC: vncserver -kill :1"
  echo "5. Future starts are headless: ./scripts/gateway/gateway.sh start"
}


cmd_vnc_config_api() {
  cd "$PROJECT_DIR"
  echo "=== Configure Gateway API Settings (One-Time VNC Setup) ==="
  echo ""

  if ! _gateway_running; then
    echo "❌ Gateway is not running!"
    echo "   Start it first: ./scripts/gateway/gateway.sh start-vnc"
    exit 1
  fi

  echo "✅ Gateway is running"
  echo ""

  VNC_DISPLAY=":1"
  if ! pgrep -f "Xvnc.*${VNC_DISPLAY}" >/dev/null 2>&1; then
    echo "Starting VNC server..."
    vncserver ${VNC_DISPLAY} -geometry 1024x768 -depth 24
    echo "✅ VNC server started"
  else
    echo "✅ VNC server already running"
  fi

  SERVER_IP="$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost')"
  echo ""
  echo "Connect: vncviewer ${SERVER_IP}:5901"
  echo ""
  echo "In Gateway UI:"
  echo "  - Configure → Settings → API → Settings"
  echo "  - Enable 'ActiveX and Socket Clients'"
  echo "  - Socket port: ${API_PORT}"
  echo "  - Trusted IPs: 127.0.0.1"
  echo "  - Approve any 'API client needs write access' dialog (if shown)"
  echo ""
  echo "Then verify:"
  echo "  ./scripts/gateway/gateway.sh api-ready"
}


cmd_setup() {
  mode="${1:-readonly}"   # readonly or full
  ibc_mode="${2:-yes}"    # yes or no

  echo "=== IB Gateway Complete Setup ==="
  echo ""
  echo "Mode: $mode"
  echo "IBC Configuration: $ibc_mode"
  echo ""

  if [ ! -d "$IBKR_HOME" ]; then
    echo "Creating IBKR home directory: $IBKR_HOME"
    mkdir -p "$IBKR_HOME"
  fi

  if [ ! -d "$IBC_DIR" ]; then
    echo "❌ IBC directory not found: $IBC_DIR"
    echo "   Install IB Gateway + IBC into IBKR home first."
    echo "   Run: ./scripts/gateway/gateway.sh install-info"
    exit 1
  fi

  echo "1. Configuring jts.ini for API access..."
  mkdir -p "$JTS_DIR"

  if ! grep -q "SocketPort" "$JTS_DIR/jts.ini" 2>/dev/null; then
    cat >> "$JTS_DIR/jts.ini" << 'EOF'

# API Configuration for Read-Only Data Access (added automatically)
SocketPort=4002
ReadOnlyAPI=true
EnableReadOnlyAPI=true
MasterAPIclientId=0
ApiOnly=true
TrustedIPs=127.0.0.1
UseSSL=false
EOF
    echo "   ✅ API settings added"
  else
    echo "   ✅ API settings already exist"
  fi

  if [ "$ibc_mode" = "yes" ]; then
    echo ""
    echo "2. Configuring IBC (IB Controller)..."
    cd "$IBC_DIR" || exit 1

    mkdir -p "$IBC_LOG_DIR"

    if [ -f config-auto.ini ]; then
      cp config-auto.ini "config-auto.ini.backup.$(date +%Y%m%d_%H%M%S)"
    fi

    # Derive the Gateway major version from the installed Jts jars (e.g., 1037).
    tws_major=""
    shopt -s nullglob
    for jar in "$JTS_DIR/jars"/twslaunch-*.jar; do
      base="$(basename "$jar")"
      tws_major="${base#twslaunch-}"
      tws_major="${tws_major%.jar}"
      break
    done
    shopt -u nullglob
    if [ -z "${tws_major:-}" ]; then
      tws_major="1037"
    fi

    trading_mode="${IBKR_ACCOUNT_TYPE:-paper}"
    trading_mode="$(echo "$trading_mode" | tr '[:upper:]' '[:lower:]')"
    if [ "$trading_mode" != "paper" ] && [ "$trading_mode" != "live" ]; then
      trading_mode="paper"
    fi

    read_only_api="yes"
    if [ "$mode" = "full" ]; then
      read_only_api="no"
    fi

    cat > config-auto.ini << EOF
# IB Controller Configuration - Read-Only Data Access
# Reduces login prompts: set IBKR_USERNAME/IBKR_PASSWORD in .env; use ReadOnlyLogin=yes to skip 2FA for data-only.

# Credentials - MUST set in .env or you get login dialog every time
IbLoginId=${IBKR_USERNAME:-}
IbPassword=${IBKR_PASSWORD:-}

# Trading mode: paper (recommended) or live
TradingMode=${trading_mode}

# Read-only = data only, no trading. ReadOnlyLogin=yes skips 2FA prompt when IB allows (data-only mode).
ReadOnlyApi=${read_only_api}
ReadOnlyLogin=yes
EnableAPI=yes

# IB Directory (where Gateway settings are stored)
IbDir=$JTS_DIR

# Auto-accept API connections (no "Accept incoming connection?" popup)
AcceptIncomingConnectionAction=accept

# Paper account warning - auto-accept so no dialog
AcceptNonBrokerageAccountWarning=yes

# Do NOT restart daily - every restart forces a fresh login + 2FA. Set RestartDaily=yes in this file if you want daily restarts.
AutoRestart=no
RestartDaily=no

# Logging
LogComponents=yes
LogToFile=yes
EOF

    echo "   ✅ IBC configured for read-only API access"

    echo ""
    echo "3. Patching IBC start scripts for this install path..."
    ibc_ini_path="$IBC_DIR/config-auto.ini"
    _patch_ibc_start_script "$IBC_DIR/gatewaystart.sh" "$tws_major" "$ibc_ini_path" "$IBC_DIR" "$JTS_DIR" "$IBC_LOG_DIR"
    _patch_ibc_start_script "$IBC_DIR/twsstart.sh" "$tws_major" "$ibc_ini_path" "$IBC_DIR" "$JTS_DIR" "$IBC_LOG_DIR"
    _patch_ibcstart_for_standalone_layout "$IBC_DIR/scripts/ibcstart.sh"
    chmod +x "$IBC_DIR"/*.sh 2>/dev/null || true
    chmod +x "$IBC_DIR/scripts"/*.sh 2>/dev/null || true
    echo "   ✅ Start scripts updated"
  fi

  echo ""
  echo "=== Setup Complete ==="
  echo ""
  echo "Next steps:"
  echo "  1. Start IB Gateway:"
  echo "     ./scripts/gateway/gateway.sh start"
  echo "  2. Check status:"
  echo "     ./scripts/gateway/gateway.sh status"
  echo "  3. Test API handshake:"
  echo "     ./scripts/gateway/gateway.sh test-api"
  echo ""
  echo "If you get login/2FA prompts often: put IBKR_USERNAME and IBKR_PASSWORD in .env;"
  echo "  then run: ./scripts/gateway/gateway.sh reduce-login-prompts"
}


cmd_reduce_login_prompts() {
  cd "$PROJECT_DIR"
  echo "=== Reduce IBKR Gateway Login Prompts ==="
  echo ""
  _ensure_ibkr_install
  local cfg="$IBC_DIR/config-auto.ini"
  if [ ! -f "$cfg" ]; then
    echo "❌ No config found: $cfg"
    echo "   Run setup first: ./scripts/gateway/gateway.sh setup readonly yes"
    exit 1
  fi
  cp "$cfg" "${cfg}.backup.$(date +%Y%m%d_%H%M%S)"
  echo "   Backed up config to ${cfg}.backup.*"
  _set_ini_or_append() {
    local key="$1"
    local val="$2"
    if grep -q "^${key}=" "$cfg" 2>/dev/null; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$cfg"
    else
      echo "${key}=${val}" >> "$cfg"
    fi
  }
  _set_ini_or_append "RestartDaily" "no"
  _set_ini_or_append "AutoRestart" "no"
  _set_ini_or_append "ReadOnlyLogin" "yes"
  _set_ini_or_append "AcceptIncomingConnectionAction" "accept"
  _set_ini_or_append "AcceptNonBrokerageAccountWarning" "yes"
  echo "   ✅ Set RestartDaily=no, AutoRestart=no, ReadOnlyLogin=yes, AcceptIncomingConnectionAction=accept"
  echo ""
  echo "1. Ensure credentials are in .env so Gateway can auto-login:"
  echo "   IBKR_USERNAME=your_username"
  echo "   IBKR_PASSWORD=your_password"
  echo "2. Restart Gateway once so it uses the new config:"
  echo "   ./scripts/gateway/gateway.sh stop"
  echo "   ./scripts/gateway/gateway.sh start"
  echo "3. If IB still asks for 2FA: approve on the mobile app; with ReadOnlyLogin=yes it may skip 2FA on later starts (data-only)."
  echo ""
}


cmd_disable_sleep() {
  # Inlined from disable_auto_sleep.sh
  set -e
  echo "🔧 Disabling auto-sleep on Beelink..."

  if [ "${EUID:-0}" -ne 0 ]; then
    echo "⚠️  Some commands require sudo. You may be prompted for your password."
    SUDO="sudo"
  else
    SUDO=""
  fi

  echo "📱 Disabling GNOME power manager sleep timeouts..."
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || echo "  (GNOME settings not available, skipping)"
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null || echo "  (GNOME settings not available, skipping)"
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || echo "  (GNOME settings not available, skipping)"
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' 2>/dev/null || echo "  (GNOME settings not available, skipping)"

  echo "⚙️  Configuring systemd-logind..."
  LOGIND_CONF="/etc/systemd/logind.conf"
  LOGIND_CONF_BAK="/etc/systemd/logind.conf.backup.$(date +%Y%m%d_%H%M%S)"

  if [ -f "$LOGIND_CONF" ]; then
    $SUDO cp "$LOGIND_CONF" "$LOGIND_CONF_BAK"
    echo "  ✓ Backed up original config to $LOGIND_CONF_BAK"
  fi

  $SUDO tee -a "$LOGIND_CONF" > /dev/null <<EOF

# Disable auto-sleep for Market Agent (added by gateway.sh disable-sleep)
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandleSuspendKey=ignore
IdleAction=ignore
EOF

  echo "  ✓ Updated systemd-logind.conf"
  echo "🔄 Restarting systemd-logind..."
  $SUDO systemctl restart systemd-logind 2>/dev/null || echo "  ⚠️  Could not restart systemd-logind (may require reboot)"

  echo "🚫 Masking sleep targets..."
  $SUDO systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || echo "  ⚠️  Could not mask sleep targets"

  echo "⏸️  Setting idle action to ignore..."
  $SUDO systemctl set-property --runtime systemd-logind.service IdleAction=ignore 2>/dev/null || echo "  ⚠️  Could not set idle action"

  if command -v xset >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    echo "🖥️  Disabling X11 DPMS (Display Power Management)..."
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
    echo "  ✓ Disabled X11 screen saver and DPMS"
  fi

  if command -v systemd-inhibit >/dev/null 2>&1; then
    echo "🔒 systemd-inhibit available (can be used to prevent sleep)"
  fi

  echo ""
  echo "✅ Auto-sleep disabled!"
  echo ""
  echo "📝 Summary:"
  echo "  • GNOME power manager: Sleep disabled"
  echo "  • systemd-logind: Sleep actions ignored"
  echo "  • Sleep targets: Masked"
  echo ""
  echo "⚠️  Note: Some changes may require a reboot to take full effect."
}


cmd_install_info() {
  cd "$PROJECT_DIR"
  echo "=== IBKR Gateway Install Info ==="
  echo ""
  echo "IBKR home: $IBKR_HOME"
  echo ""
  echo "Expected layout:"
  echo "  $IBKR_HOME/ibc"
  echo "  $IBKR_HOME/Jts"
  echo ""
  echo "Configure the location with:"
  echo "  export PEARLALGO_IBKR_HOME=/opt/ibkr"
  echo "  ./scripts/gateway/gateway.sh --ibkr-home /opt/ibkr status"
  echo ""
  echo "If these folders are missing, install IB Gateway + IBC into IBKR home"
  echo "and then run:"
  echo "  ./scripts/gateway/gateway.sh setup"
}

cmd_doctor() {
  cd "$PROJECT_DIR"
  echo "=== IBKR Gateway Doctor ==="
  echo ""
  echo "IBKR home: $IBKR_HOME"
  echo "Expected:"
  echo "  IBC: $IBC_DIR/gatewaystart.sh"
  echo "  Jts: $JTS_DIR"
  echo ""

  if command -v java >/dev/null 2>&1; then
    echo "✅ Java: $(java -version 2>&1 | head -1)"
  else
    echo "❌ Java not found on PATH (need Java 17+ for Gateway/IBC)"
  fi

  if command -v Xvfb >/dev/null 2>&1; then
    echo "✅ Xvfb: installed"
  else
    echo "⚠️  Xvfb: not found (headless start may fail)"
  fi

  echo ""

  if [ -f "$IBC_DIR/gatewaystart.sh" ]; then
    echo "✅ IBC: gatewaystart.sh present"
  else
    echo "❌ IBC: missing gatewaystart.sh"
  fi

  if [ -d "$JTS_DIR" ]; then
    echo "✅ Jts: directory present"
  else
    echo "❌ Jts: directory missing"
  fi

  echo ""
  echo "Quick next steps:"
  echo "  - Install: ./scripts/gateway/gateway.sh install"
  echo "  - Configure: ./scripts/gateway/gateway.sh setup"
  echo "  - Start: ./scripts/gateway/gateway.sh start"
}

_download_file() {
  local url="$1"
  local dest="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -L --fail --retry 3 --retry-delay 2 -o "$dest" "$url"
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -O "$dest" "$url"
    return 0
  fi

  echo "❌ Neither curl nor wget is available to download files"
  return 1
}

cmd_install() {
  variant="${1:-stable}"  # stable|latest
  ibc_version="${2:-3.23.0}"

  cd "$PROJECT_DIR"
  echo "=== Installing IB Gateway + IBC ==="
  echo ""
  echo "IBKR home: $IBKR_HOME"
  echo "Variant: $variant"
  echo "IBC version: $ibc_version"
  echo ""

  mkdir -p "$IBKR_HOME" "$IBKR_HOME/ibc" "$IBKR_HOME/Jts"
  _set_ibkr_paths

  arch="$(uname -m 2>/dev/null || echo unknown)"
  if [ "$arch" = "x86_64" ] || [ "$arch" = "amd64" ]; then
    linux_arch="linux-x64"
  elif [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then
    linux_arch="linux-arm"
  else
    echo "❌ Unsupported architecture for automated install: $arch"
    echo "   Download the installer manually from:"
    echo "   https://www.interactivebrokers.com/en/trading/ib-gateway-download.php"
    exit 1
  fi

  if [ "$variant" != "stable" ] && [ "$variant" != "latest" ]; then
    echo "❌ Unknown variant: $variant (use stable|latest)"
    exit 1
  fi

  ibgw_file="ibgateway-${variant}-standalone-${linux_arch}.sh"
  ibgw_url="https://download2.interactivebrokers.com/installers/ibgateway/${variant}-standalone/${ibgw_file}"
  ibgw_installer="$IBKR_HOME/${ibgw_file}"

  echo "1) Downloading IB Gateway installer..."
  echo "   $ibgw_url"
  if [ ! -f "$ibgw_installer" ]; then
    _download_file "$ibgw_url" "$ibgw_installer"
    chmod +x "$ibgw_installer" || true
  else
    echo "   ✅ Already downloaded: $ibgw_installer"
  fi

  echo ""
  echo "2) Installing IB Gateway into: $JTS_DIR"
  echo "   (This uses install4j unattended mode: -q -dir <path>)"
  chmod +x "$ibgw_installer" 2>/dev/null || true
  "$ibgw_installer" -q -dir "$JTS_DIR" -overwrite -console || {
    echo ""
    echo "❌ IB Gateway installer failed."
    echo "   Try console mode for more detail:"
    echo "     $ibgw_installer -c"
    echo "   Or run GUI/VNC install and point it at: $JTS_DIR"
    exit 1
  }

  echo ""
  echo "3) Downloading IBC (IB Controller)..."
  ibc_zip="IBCLinux-${ibc_version}.zip"
  ibc_url="https://github.com/IbcAlpha/IBC/releases/download/${ibc_version}/${ibc_zip}"
  ibc_zip_path="$IBKR_HOME/${ibc_zip}"
  echo "   $ibc_url"
  if [ ! -f "$ibc_zip_path" ]; then
    _download_file "$ibc_url" "$ibc_zip_path"
  else
    echo "   ✅ Already downloaded: $ibc_zip_path"
  fi

  echo ""
  echo "4) Installing IBC into: $IBC_DIR"
  mkdir -p "$IBC_DIR"

  # Preserve local configs if present.
  ts="$(date +%Y%m%d_%H%M%S)"
  if [ -f "$IBC_DIR/config.ini" ]; then
    cp "$IBC_DIR/config.ini" "$IBC_DIR/config.ini.backup.${ts}" || true
  fi
  if [ -f "$IBC_DIR/config-auto.ini" ]; then
    cp "$IBC_DIR/config-auto.ini" "$IBC_DIR/config-auto.ini.backup.${ts}" || true
  fi

  python3 -m zipfile -e "$ibc_zip_path" "$IBC_DIR" >/dev/null 2>&1 || {
    echo "❌ Failed to extract IBC zip (need Python 3 with zipfile module)"
    exit 1
  }

  chmod +x "$IBC_DIR"/*.sh 2>/dev/null || true
  chmod +x "$IBC_DIR/scripts"/*.sh 2>/dev/null || true

  if [ ! -f "$IBC_DIR/gatewaystart.sh" ]; then
    echo "❌ IBC install did not produce gatewaystart.sh at: $IBC_DIR/gatewaystart.sh"
    echo "   Check the extracted folder contents."
    exit 1
  fi

  echo ""
  echo "✅ Install complete."
  echo ""
  echo "Next:"
  echo "  ./scripts/gateway/gateway.sh setup"
  echo "  ./scripts/gateway/gateway.sh start"
  echo "  ./scripts/gateway/gateway.sh status"
}


print_help() {
  cat <<'EOF'
Usage:
  ./scripts/gateway/gateway.sh [--ibkr-home PATH] <command>

Commands:
  start               Start Gateway headless via IBC (Xvfb DISPLAY=:99)
  start-vnc           Start Gateway via IBC on VNC display (:1)
  stop                Stop Gateway (IBC)
  status              Check Gateway status
  api-ready           Check API port readiness (exit 0 if ready)
  monitor             Monitor until API is ready (max 5 minutes)
  tws-conflict         Detect TWS/Gateway conflicts and Error 162 hints
  test-api            Attempt short API connect using ib_insync
  2fa-status          Check whether 2FA is required (log-based)
  wait-2fa            Wait for 2FA approval (mobile; max 10 minutes)
  complete-2fa        Start VNC (if needed) and print 2FA entry instructions
  auto-2fa [CODE]     Attempt to auto-enter 2FA code (requires xdotool)
  doctor              Print environment + install diagnostics
  install [variant]   Download/install IB Gateway + IBC into IBKR home (variant=stable|latest)
  install-info        Print IBKR install expectations and paths
  setup [mode] [ibc]  One-time gateway + IBC setup (mode=readonly/full, ibc=yes/no)
  vnc-setup           One-time VNC setup for manual login
  vnc-config-api      One-time API config guidance via VNC
  disable-sleep       Disable auto-sleep (host helper)
  reduce-login-prompts  Patch IBC config to reduce login/2FA prompts (RestartDaily=no, ReadOnlyLogin=yes, etc.)
  help            Show this help
EOF
}

ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ibkr-home)
      if [ -z "${2:-}" ]; then
        echo "❌ Missing value for --ibkr-home"
        exit 1
      fi
      IBKR_HOME="$2"
      shift 2
      ;;
    --ibkr-home=*)
      IBKR_HOME="${1#*=}"
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

set -- "${ARGS[@]}"
_set_ibkr_paths

cmd="${1:-help}"
shift || true

case "$cmd" in
  help|-h|--help)
    print_help
    exit 0
    ;;
  start)
    cmd_start "$@"
    ;;
  start-vnc)
    cmd_start_vnc "$@"
    ;;
  stop)
    cmd_stop "$@"
    ;;
  status)
    cmd_status "$@"
    ;;
  api-ready)
    cmd_api_ready "$@"
    ;;
  tws-conflict)
    cmd_tws_conflict "$@"
    ;;
  test-api)
    cmd_test_api "$@"
    ;;
  install-info)
    cmd_install_info "$@"
    ;;
  doctor)
    cmd_doctor "$@"
    ;;
  install)
    cmd_install "$@"
    ;;
  2fa-status)
    cmd_2fa_status "$@"
    ;;
  wait-2fa)
    cmd_wait_2fa "$@"
    ;;
  complete-2fa)
    cmd_complete_2fa "$@"
    ;;
  auto-2fa)
    cmd_auto_2fa "$@"
    ;;
  monitor)
    cmd_monitor "$@"
    ;;
  setup)
    cmd_setup "$@"
    ;;
  vnc-setup)
    cmd_vnc_setup "$@"
    ;;
  vnc-config-api)
    cmd_vnc_config_api "$@"
    ;;
  disable-sleep)
    cmd_disable_sleep "$@"
    ;;
  reduce-login-prompts)
    cmd_reduce_login_prompts "$@"
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    echo >&2
    print_help >&2
    exit 2
    ;;
esac


