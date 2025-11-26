from __future__ import annotations

"""
Minimal CLI placeholder.
The legacy Moon-style CLI lives in legacy/src/pearlalgo/cli.py; this stub keeps imports working and
points users to the futures entry scripts under scripts/.
"""

import sys


def main(_argv: list[str] | None = None) -> int:
    msg = (
        "Futures-first CLI is script-based.\n"
        "- Signals: scripts/run_daily_signals.py\n"
        "- Live paper: scripts/live_paper_loop.py\n"
        "- Risk monitor: scripts/risk_monitor.py\n"
        "- Daily report: scripts/daily_report.py\n"
        "Legacy CLI (moon-era backtesting/agents) is under legacy/src/pearlalgo/cli.py"
    )
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
