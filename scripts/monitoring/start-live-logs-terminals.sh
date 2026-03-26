#!/bin/sh
# Open 2–3 xfce4-terminal windows with live, colorized logs and dark transparent theme.
# Use with autostart or run manually.

export PATH="/usr/bin:/bin:${PATH}"
PROJECT_ROOT="/home/pearlalgo/PearlAlgoWorkspace"
SCRIPT_DIR="${PROJECT_ROOT}/scripts/monitoring"
RUNNER="${SCRIPT_DIR}/run-journalctl-colored.sh"

# Apply dark theme + transparency before opening terminals
if [ -x "${SCRIPT_DIR}/enable-terminal-transparency.sh" ]; then
  PEARLALGO_PROJECT_ROOT="${PROJECT_ROOT}" "${SCRIPT_DIR}/enable-terminal-transparency.sh"
fi

# Geometry: COLUMNSxROWS+XOFF+YOFF (~1920 width: 3 panes)
G1="90x30+0+0"
G2="90x30+640+0"
G3="90x30+1280+0"

if command -v xfce4-terminal >/dev/null 2>&1; then
  xfce4-terminal --disable-server --geometry="$G1" -T "PearlAlgo Agent"    --hold -e "${RUNNER} pearlalgo-agent"
  sleep 0.5
  xfce4-terminal --disable-server --geometry="$G2" -T "PearlAlgo API"      --hold -e "${RUNNER} pearlalgo-api"
elif command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal --geometry=90x30+0+0    --title "PearlAlgo Agent"    -- "${RUNNER} pearlalgo-agent"
  sleep 0.5
  gnome-terminal --geometry=90x30+640+0  --title "PearlAlgo API"      -- "${RUNNER} pearlalgo-api"
else
  echo "No xfce4-terminal or gnome-terminal found."
  exit 1
fi
