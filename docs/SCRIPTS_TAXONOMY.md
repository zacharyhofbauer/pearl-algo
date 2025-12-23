# Scripts Taxonomy and Canonical Entry Points

This document standardizes the roles of all scripts under `scripts/` and identifies the canonical entry points.

## Lifecycle (`scripts/lifecycle/`)

- `start_nq_agent_service.sh`
  - **Role**: Canonical way to start the NQ Agent Service.
  - **Behavior**: Activates `.venv` if present, verifies `pearlalgo` is importable, supports foreground and `--background` modes, manages PID file in `logs/nq_agent.pid`.
- `stop_nq_agent_service.sh`
  - **Role**: Canonical way to stop the NQ Agent Service.
  - **Behavior**: Uses PID file if available, falls back to `pgrep -f "pearlalgo.nq_agent.main"`.
- `check_nq_agent_status.sh`
  - **Role**: Check process and basic state (PID, uptime, state file summary, gateway status).

## Gateway (`scripts/gateway/`)

Gateway scripts orchestrate IBKR Gateway lifecycle and 2FA flows. They do **not** contain trading logic.

Key scripts (to keep as canonical):

- `start_ibgateway_ibc.sh`, `stop_ibgateway_ibc.sh` – start/stop Gateway via IBC.
- `check_gateway_status.sh` – check if Gateway is running.
- `check_api_ready.sh`, `check_gateway_2fa_status.sh`, `test_api_connection.sh` – verify authentication and API connectivity.
- `check_tws_conflict.sh` – detect TWS/Gateway conflicts.
- `auto_2fa.sh`, `wait_for_2fa_approval.sh`, `complete_2fa_vnc.sh`, `setup_vnc_for_login.sh`, `configure_gateway_api_vnc.sh` – 2FA + VNC workflows.
- `monitor_until_ready.sh` – wait for Gateway readiness.
- `disable_auto_sleep.sh` – prevent OS sleep (environmental helper).
- `setup_ibgateway.sh` – initial setup/orchestration.
- `vnc_terminal_helper.md` – helper doc for VNC usage.

## Telegram (`scripts/telegram/`)

- `start_command_handler.sh`
  - **Role**: Canonical entry to start Telegram Command Handler.
  - **Behavior**: Changes to project root, activates `.venv` if present, selects `.venv/bin/python3` when available, verifies `pearlalgo` import, ensures only one handler instance via `pgrep -f "telegram_command_handler"`, then runs `-m pearlalgo.nq_agent.telegram_command_handler`.
- `check_command_handler.sh`
  - **Role**: Check if command handler process is running and show PIDs.
- `set_bot_commands.py`
  - **Role**: Helper to set BotFather commands via Telegram API using `python-telegram-bot`.

## Testing (`scripts/testing/`)

- `test_all.py`
  - **Role**: Unified test runner supporting different modes (e.g. `telegram`, `ibkr`, `strategy`).
- `run_tests.sh`
  - **Role**: Developer convenience script; activates `.venv` if present, ensures package is installed, then calls `test_all.py`.
- `test_nq_agent_with_mock.py`
  - **Role**: Integration tests using mock data provider.
- `test_signal_generation.py`, `test_signal_starvation_fixes.py`
  - **Role**: Strategy‑level unit tests.
- `test_data_quality.py`, `test_e2e_simulation.py`
  - **Role**: Data‑quality and end‑to‑end tests.
- `test_telegram_notifications.py`
  - **Role**: Validate Telegram notification formatting and sending behavior (using mocks/fixtures).
- `smoke_test_ibkr.py`
  - **Role**: Quick connectivity and entitlement smoke test for IBKR.
- `validate_strategy.py`
  - **Role**: Validate strategy outputs/assumptions for given historical data.
- `check_signals.py`
  - **Role**: Diagnostic tool to check signals file format, count, and validity. Useful for troubleshooting signal persistence issues.

## Maintenance / Misc

At present, all scripts fall into the four categories above. If new scripts are added, they should be placed under one of these directories and follow the patterns described here:

- Always `cd` to project root at startup.
- Prefer the project virtual environment (`.venv/bin/python3`) when running Python modules.
- Use `python -m pearlalgo...` style entry points; avoid hard‑coded paths.
- Keep business logic in Python modules, not in shell scripts.

This taxonomy should be updated whenever a new script is added or an existing one is retired.
