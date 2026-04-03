# PearlAlgo monitoring scripts

## Live log terminals (autostart)

- **`start-live-logs-terminals.sh`** – Opens 2 terminals with live, colorized logs:
  - **Agent** – `journalctl -u pearlalgo-agent -f`
  - **API** – `journalctl -u pearlalgo-api -f`

- **`run-journalctl-colored.sh`** – Wrapper: `run-journalctl-colored.sh <unit>` runs `journalctl -f -o cat -q` piped through the colorizer. Checks that the unit exists.

- **`colorize-logs.awk`** – AWK script that colors log lines by level:
  - **ERROR** = red, **WARNING** = yellow, **INFO** = green, **DEBUG** = dim
  - Timestamps = cyan, Exception/failed = magenta, success/OK/placed = green

- **`enable-terminal-transparency.sh`** – Applies dark theme + transparency:
  - Copies `terminalrc-pearlalgo-dark` to `~/.config/xfce4/terminal/terminalrc`
  - Sets xfconf transparency (newer xfce4-terminal)
  - **Compositor must be enabled**: Settings → Window Manager Tweaks → Compositor

- **`terminalrc-pearlalgo-dark`** – Dark theme (background `#1a1a2e`, light text, 85% opacity with transparency).

## Tuning

- **Geometry** – Edit `G1`/`G2`/`G3` in `start-live-logs-terminals.sh` (e.g. `90x30+0+0` = 90 cols, 30 rows, position 0,0).
- **Add a 4th window** – Append another `xfce4-terminal ... -e "${RUNNER} ibkr-gateway"` (and a new `G4`).
- **Colors** – Edit `colorize-logs.awk` (ANSI codes) or `terminalrc-pearlalgo-dark` (palette).

## Other

- **`monitor.py`** – One-shot health check (agent, gateway, API, webapp) with structured exit codes.
- **`dashboard.sh`** – One-shot status (services + monitor + doctor).
- **`start-dashboard-terminal.sh`** – Opens one terminal with refreshing dashboard (replaced by live logs at login).
