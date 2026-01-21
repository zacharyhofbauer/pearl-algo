# AI Patch Guide

OpenAI-backed patch generation for Telegram using the **AI Patch Wizard** (recommended).

## Quick Start

### 1. Install the LLM Extra

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e ".[llm]"
```

### 2. Set OpenAI Credentials

Add to your `.env` file:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_MAX_TOKENS=4096
OPENAI_TIMEOUT=120
```

### 3. Restart the Command Handler

```bash
./scripts/telegram/restart_command_handler.sh --background
```

## Usage

In Telegram:

- `/start` → **⚙️ Settings** → **🧩 AI Patch Wizard**
- Pick a file (or **Other file (type path)**)
- Send the instruction text (example: `add jitter to retry backoff`)

The wizard returns a **unified diff patch** for review.

## Notes

- The patch wizard does **not** apply changes automatically.
- Paths outside the repo or in blocked dirs (e.g., `data/`, `logs/`, `.env`, `.venv/`, `.git/`) are rejected.
- Telegram has message size limits; very large diffs may be truncated.

## Advanced (intentional)

The codebase includes an internal `/ai_patch` handler method, but the supported operator
path is the **AI Patch Wizard** in the Settings menu.
