# GitHub Codespaces / Devcontainer Guide

This project includes a devcontainer configuration for GitHub Codespaces and VS Code Dev Containers.

## Quick Start

1. **Open in Codespaces** (GitHub) or **Reopen in Container** (VS Code)
2. Wait for `postCreateCommand` to complete (`make install`)
3. Configure secrets (see below)
4. Run health checks

## Codespaces Secrets

Set these secrets in your GitHub Codespaces settings (repo or user level):

| Secret | Description | Example |
|--------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `123456789:ABC...` |
| `TELEGRAM_CHAT_ID` | Your chat ID (numeric) | `123456789` |
| `IBKR_HOST` | IBKR Gateway host | `127.0.0.1` |
| `IBKR_PORT` | IBKR Gateway API port | `4002` |

**Note:** Do not commit `.env` files. The devcontainer copies `env.example` to `.env` on creation - update with real values or use Codespaces secrets.

To use Codespaces secrets in your `.env`:

```bash
# Populate .env from Codespaces secrets
cat > .env << EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
IBKR_HOST=${IBKR_HOST:-127.0.0.1}
IBKR_PORT=${IBKR_PORT:-4002}
IBKR_CLIENT_ID=10
IBKR_DATA_CLIENT_ID=11
PEARLALGO_DATA_PROVIDER=ibkr
EOF
```

## Startup Commands

### 1. Start Telegram Command Handler (menu UI)

```bash
./scripts/telegram/start_command_handler.sh --background
```

### 2. Start IBKR Gateway (if IBC is configured)

```bash
./scripts/gateway/gateway.sh start
./scripts/gateway/gateway.sh status
```

### 3. Start Market Agent

```bash
./scripts/lifecycle/agent.sh start --market NQ --background
./scripts/lifecycle/check_agent_status.sh --market NQ
```

## Health Checks

### Quick health check (all services)

```bash
./scripts/ops/quick_status.sh --market NQ
```

### Run CI checks locally

```bash
make ci
```

This runs: `ruff-bugs arch secrets smoke audit test`

### Targeted Health tests

```bash
# Health monitor tests
pytest tests/test_health_monitor.py -v

# Telegram message formatting
pytest tests/test_telegram_message_limits.py -v

# UI contract tests
pytest tests/test_telegram_ui_contract.py -v
```

## Telegram Live Verification

1. Ensure Telegram credentials are configured
2. Start the command handler: `./scripts/telegram/start_command_handler.sh`
3. In Telegram, send `/start` to your bot
4. Navigate to **🛡️ Health** and verify each button:
   - **Gateway**: Shows process + port status
   - **Connection**: Shows connection state
   - **Data**: Shows data age and staleness
   - **Status**: Full system dashboard
   - **Doctor**: Diagnostics + test buttons

## Included System Dependencies

The devcontainer includes:

- **Python 3.12** (matches `pyproject.toml`)
- **OpenJDK 17** (for IBKR Gateway/IBC)
- **Xvfb** (headless display for Gateway)
- **jq** (JSON parsing in health scripts)
- **iproute2** (provides `ss` for port checks)

## Ports

| Port | Service |
|------|---------|
| 4002 | IBKR Gateway API |
| 5901 | VNC Display (if configured) |

## Troubleshooting

### Gateway won't start

```bash
# Check Java
java -version

# Check Xvfb
pgrep -f Xvfb || Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
```

### Pearl Algo Web App screenshot capture (optional)

Telegram dashboard screenshots use Playwright:

```bash
pip install playwright
playwright install chromium
```

### Missing dependencies

```bash
make install
```
