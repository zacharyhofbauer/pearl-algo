#!/bin/sh
# Launch PearlAlgo CLI dashboard in a terminal (for autostart or manual use).
# Refreshes every 30 seconds. Close the terminal to stop.
# Uses /bin/sh so it works when bash is not installed (e.g. minimal Ubuntu).

export PATH="/usr/bin:/bin:${PATH}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DASHBOARD="${PROJECT_ROOT}/scripts/monitoring/dashboard.sh"
REFRESH=30

run_foreground() {
    cd "$PROJECT_ROOT" || exit 1
    while true; do
        clear
        "$DASHBOARD"
        sleep "$REFRESH"
    done
}

if [ "$1" = "foreground" ]; then
    run_foreground
    exit 0
fi

# Open a new terminal running the dashboard loop inline (no script path to exec).
# This avoids "Failed to execute child process ... No such file or directory"
# when the terminal tries to exec a script path.
# Single-quoted so the terminal runs: sh -c 'cd ... && while ...; do ...; done'
if command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title "PearlAlgo Dashboard" -e "sh -c 'cd ${PROJECT_ROOT} && while true; do clear; ${DASHBOARD}; sleep ${REFRESH}; done'"
elif command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title "PearlAlgo Dashboard" -- sh -c "cd ${PROJECT_ROOT} && while true; do clear; ${DASHBOARD}; sleep ${REFRESH}; done"
elif command -v xterm >/dev/null 2>&1; then
    xterm -title "PearlAlgo Dashboard" -e "sh -c 'cd ${PROJECT_ROOT} && while true; do clear; ${DASHBOARD}; sleep ${REFRESH}; done'"
else
    run_foreground
fi
