# PEARLalgo Cheat Sheet

> **Goal:** One-page operational quick reference for daily use.
> For full details, see `NQ_AGENT_GUIDE.md`, `GATEWAY.md`, and `TELEGRAM_GUIDE.md`.

---

## 1. Environment & Setup (once per machine)

- **Create venv & install**
  ```bash
  cd ~/pearlalgo-dev-ai-agents
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -e .
  ```

- **`.env` essentials**
  ```bash
  TELEGRAM_BOT_TOKEN=your_bot_token_here
  TELEGRAM_CHAT_ID=your_chat_id_here

  IBKR_HOST=127.0.0.1
  IBKR_PORT=4002
  IBKR_CLIENT_ID=10
  IBKR_DATA_CLIENT_ID=11

  PEARLALGO_DATA_PROVIDER=ibkr
  PEARLALGO_LOG_LEVEL=INFO
  ```

---

## 2. Daily Start-Up Flow (order matters)

1. **Open terminal & activate venv**
   ```bash
   cd ~/pearlalgo-dev-ai-agents
   source .venv/bin/activate
   ```

2. **Start IBKR Gateway**
   ```bash
   ./scripts/gateway/start_ibgateway_ibc.sh
   ./scripts/gateway/check_gateway_status.sh   # expect: RUNNING + API READY
   ```

3. **Start NQ Agent Service**
   - **Foreground (see logs)**
     ```bash
     ./scripts/lifecycle/start_nq_agent_service.sh
     ```
   - **Background**
     ```bash
     ./scripts/lifecycle/start_nq_agent_service.sh --background
     ./scripts/lifecycle/check_nq_agent_status.sh
     ```

4. **Start Telegram Command Handler** (for `/status`, `/signals`, etc.)
   ```bash
   ./scripts/telegram/start_command_handler.sh
   ```

---

## 3. Core Commands You Actually Use

- **Service lifecycle**
  ```bash
  ./scripts/lifecycle/start_nq_agent_service.sh          # start (fg)
  ./scripts/lifecycle/start_nq_agent_service.sh --background
  ./scripts/lifecycle/stop_nq_agent_service.sh           # stop
  ./scripts/lifecycle/check_nq_agent_status.sh           # status
  ```

- **Gateway**
  ```bash
  ./scripts/gateway/start_ibgateway_ibc.sh
  ./scripts/gateway/stop_ibgateway_ibc.sh
  ./scripts/gateway/check_gateway_status.sh
  ```

- **Telegram**
  ```bash
  ./scripts/telegram/start_command_handler.sh            # listen to commands
  ./scripts/telegram/check_command_handler.sh            # is it running?
  python3 scripts/telegram/set_bot_commands.py           # (re)push /status, /signals, ...
  ```

---

## 4. Telegram Usage (what to expect)

- **Works even without command handler:**
  - Startup / shutdown notifications
  - Heartbeats and periodic status summaries
  - Signal alerts, error/circuit‑breaker alerts

- **Requires command handler running:**
  - `/status` – Agent Status card with inline buttons
  - `/signals` – Recent signals list
  - `/performance` – 7‑day performance summary
  - `/help` – command help
  - `/pause`, `/resume` – **informational only**; actual control is via lifecycle scripts

---

## 5. Quick Troubleshooting

- **No Telegram responses to `/status`:**
  ```bash
  ./scripts/telegram/check_command_handler.sh
  ./scripts/lifecycle/check_nq_agent_status.sh
  ```

- **No market data / no signals:**
  ```bash
  ./scripts/gateway/check_gateway_status.sh
  cat data/nq_agent_state/state.json | jq .buffer_size
  ```

- **Service looks stuck / weird:**
  ```bash
  ./scripts/lifecycle/check_nq_agent_status.sh
  ./scripts/lifecycle/stop_nq_agent_service.sh
  ./scripts/lifecycle/start_nq_agent_service.sh
  ```

- **Verify Telegram config quickly:**
  ```bash
  echo $TELEGRAM_BOT_TOKEN
  echo $TELEGRAM_CHAT_ID
  python3 scripts/testing/test_all.py telegram
  ```

---

## 6. Where things live

- **Config**: `config/config.yaml`, `.env`
- **State**: `data/nq_agent_state/` (`state.json`, `signals.jsonl`, `performance.json`)
- **Services & scripts**: `scripts/lifecycle/`, `scripts/gateway/`, `scripts/telegram/`
- **Deep-dive docs**: `NQ_AGENT_GUIDE.md`, `GATEWAY.md`, `TELEGRAM_GUIDE.md`, `PROJECT_SUMMARY.md`

This cheat sheet is the **primary quick-reference** for PEARLalgo operations. Keep it updated as workflows evolve.