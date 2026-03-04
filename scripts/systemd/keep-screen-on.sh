#!/bin/bash
# Keep display on (no blanking, no DPMS) for Pearl Algo Corsair Ubuntu.
# Run at session start via ~/.config/autostart/pearlalgo-keep-screen-on.desktop

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

# Wait for display to be ready (autostart can run before X is up)
for i in 1 2 3 4 5 6 7 8 9 10; do
  xset q &>/dev/null && break
  sleep 2
done

# Disable screen blanking and screen saver
xset s off 2>/dev/null
xset s noblank 2>/dev/null
# Disable DPMS (Energy Star) power saving
xset -dpms 2>/dev/null
# Prevent screen from ever timing out (0 = never)
xset s 0 0 2>/dev/null

exit 0
