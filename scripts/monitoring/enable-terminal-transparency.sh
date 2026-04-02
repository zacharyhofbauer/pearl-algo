#!/bin/sh
# Apply dark theme + transparency for xfce4-terminal (live-log windows).
# Copies project's terminalrc so colors and transparency are consistent.
# Requires compositor enabled: Settings → Window Manager Tweaks → Compositor.

TERMINALRC="${HOME}/.config/xfce4/terminal/terminalrc"
PROJECT_ROOT="${PEARLALGO_PROJECT_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
THEME_RC="${PROJECT_ROOT}/scripts/monitoring/terminalrc-pearlalgo-dark"

mkdir -p "${HOME}/.config/xfce4/terminal"

# Apply dark theme + transparency from project's terminalrc
if [ -f "$THEME_RC" ]; then
  cp "$THEME_RC" "$TERMINALRC"
fi

# Ensure transparency in xfconf (newer xfce4-terminal)
if command -v xfconf-query >/dev/null 2>&1; then
  xfconf-query -c xfce4-terminal -p /misc-background-darkness -n -t double -s 0.85 2>/dev/null
  xfconf-query -c xfce4-terminal -p /misc-transparent-background -n -t bool -s true 2>/dev/null
fi
