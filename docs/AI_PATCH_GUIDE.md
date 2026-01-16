# AI Patch Guide

OpenAI-backed patch generation for Telegram using `/ai_patch`.

## Quick Start

### 1. Install the LLM Extra

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e .[llm]
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
pkill -f telegram_command_handler
./scripts/telegram/start_command_handler.sh --background
```

## Usage

```bash
/ai_patch <relative_path> <instruction>
```

Example:

```
/ai_patch src/pearlalgo/utils/retry.py add jitter
```

## Notes

- `/ai_patch` returns a unified diff. Review before applying.
- Paths outside the repo or in blocked dirs (e.g., `data/`, `logs/`) are rejected.
