# Telegram Quick Start

This document has been condensed. The **canonical Telegram reference** is now:

- [`TELEGRAM_GUIDE.md`](TELEGRAM_GUIDE.md)

Use that guide for:
- Setting up commands in BotFather
- Starting the Telegram Command Handler
- Understanding what `/status`, `/signals`, `/performance`, `/pause`, `/resume` do

If you only need the fastest possible setup:

1. Set commands via BotFather using the list in `TELEGRAM_GUIDE.md`.
2. Start the command handler:
   ```bash
   cd ~/pearlalgo-dev-ai-agents
   ./scripts/telegram/start_command_handler.sh
   ```
3. In Telegram, send:
   ```
   /status
   ```
   You should see an Agent Status card.

For all details and troubleshooting, see `TELEGRAM_GUIDE.md`.

