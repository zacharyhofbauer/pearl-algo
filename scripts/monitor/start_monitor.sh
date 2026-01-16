#!/bin/bash
# ============================================================================
# Start Pearl Algo Monitor (PyQt6 GUI)
#
# Usage:
#   ./scripts/monitor/start_monitor.sh                 # foreground
#   ./scripts/monitor/start_monitor.sh --background    # background
#
# Optional flags:
#   --display=:0            Force X11 display (default: auto-detect)
#   --xauthority=/path      Force Xauthority (default: $XAUTHORITY or ~/.Xauthority)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/pearl_algo_monitor.log"
PID_FILE="$LOG_DIR/pearl_algo_monitor.pid"

BACKGROUND=false
DISPLAY_OVERRIDE=""
XAUTH_OVERRIDE=""

for arg in "$@"; do
  case "$arg" in
    --background|-b) BACKGROUND=true ;;
    --foreground|-f) BACKGROUND=false ;;
    --display=*) DISPLAY_OVERRIDE="${arg#*=}" ;;
    --xauthority=*) XAUTH_OVERRIDE="${arg#*=}" ;;
  esac
done

cd "$PROJECT_DIR"
mkdir -p "$LOG_DIR"

# Use venv python if available
PYTHON_CMD="python3"
if [ -x ".venv/bin/python3" ]; then
  PYTHON_CMD=".venv/bin/python3"
fi

# Verify pearlalgo is importable
if ! "$PYTHON_CMD" -c "import pearlalgo" >/dev/null 2>&1; then
  echo "ERROR: pearlalgo package not found in this Python environment."
  echo "Fix: activate venv or run: pip install -e ."
  exit 1
fi

# Refuse to start if already running
if pgrep -f "pearlalgo\\.monitor" >/dev/null 2>&1; then
  echo "ERROR: Monitor already running."
  echo "Stop: pkill -f pearlalgo.monitor"
  exit 1
fi

# Determine DISPLAY
DISPLAY_TO_USE=""
if [ -n "$DISPLAY_OVERRIDE" ]; then
  DISPLAY_TO_USE="$DISPLAY_OVERRIDE"
elif [ -n "${DISPLAY:-}" ]; then
  DISPLAY_TO_USE="$DISPLAY"
else
  # Prefer physical desktop display first (:0, :1), then fallback (:99) if present.
  for d in :0 :1 :99; do
    num="${d#:}"
    if [ -S "/tmp/.X11-unix/X${num}" ]; then
      DISPLAY_TO_USE="$d"
      break
    fi
  done
fi

if [ -z "$DISPLAY_TO_USE" ]; then
  echo "ERROR: DISPLAY is not set and no X display socket found under /tmp/.X11-unix/."
  echo "Run from a desktop session, or pass --display=:0 (and ensure Xauthority permissions)."
  exit 1
fi

# Determine XAUTHORITY (needed when launching GUI from SSH onto an existing desktop session)
XAUTH_TO_USE=""
if [ -n "$XAUTH_OVERRIDE" ]; then
  XAUTH_TO_USE="$XAUTH_OVERRIDE"
elif [ -n "${XAUTHORITY:-}" ]; then
  XAUTH_TO_USE="$XAUTHORITY"
elif [ -f "$HOME/.Xauthority" ]; then
  XAUTH_TO_USE="$HOME/.Xauthority"
fi

# Determine Qt platform backend (X11 vs Wayland)
QT_PLATFORM="xcb"
if [ -n "${WAYLAND_DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  QT_PLATFORM="wayland"
fi

# Basic dependency guard for Qt xcb plugin
if [ "$QT_PLATFORM" = "xcb" ] && command -v dpkg >/dev/null 2>&1; then
  if ! dpkg -s libxcb-cursor0 >/dev/null 2>&1; then
    echo "ERROR: Missing dependency for X11 (Qt xcb plugin): libxcb-cursor0"
    echo "Install: sudo apt-get update && sudo apt-get install -y libxcb-cursor0"
    exit 1
  fi
fi

ENV_ARGS=("DISPLAY=$DISPLAY_TO_USE" "QT_QPA_PLATFORM=$QT_PLATFORM")
if [ -n "$XAUTH_TO_USE" ]; then
  ENV_ARGS+=("XAUTHORITY=$XAUTH_TO_USE")
fi

if [ "$BACKGROUND" = true ]; then
  nohup env "${ENV_ARGS[@]}" "$PYTHON_CMD" -m pearlalgo.monitor >>"$LOG_FILE" 2>&1 &
  MONITOR_PID=$!
  echo "$MONITOR_PID" > "$PID_FILE"

  sleep 0.5 || true
  if ps -p "$MONITOR_PID" >/dev/null 2>&1; then
    echo "Monitor started (PID $MONITOR_PID)"
    echo "DISPLAY=$DISPLAY_TO_USE QT_QPA_PLATFORM=$QT_PLATFORM"
    echo "Logs: $LOG_FILE"
    exit 0
  fi

  echo "ERROR: Monitor exited immediately."
  echo "Logs: $LOG_FILE"
  exit 1
fi

exec env "${ENV_ARGS[@]}" "$PYTHON_CMD" -m pearlalgo.monitor

