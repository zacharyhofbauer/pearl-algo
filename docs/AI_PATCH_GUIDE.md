# AI Patch Guide

> **Generate code patches from Telegram using Claude AI.**
> Fix bugs, add features, and refactor code—all from your phone.

---

## Overview

The `/ai_patch` command lets you request code changes via Telegram. Claude analyzes your files, understands the task, and returns a unified diff patch that you can apply with `git apply`.

**Why this exists:**
- Fix issues while away from your desk
- Quick iterations without opening an IDE
- Mobile-friendly development workflow
- Secure: changes are reviewed before applying

---

## Quick Start

### 1. Install the LLM Extra

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
pip install -e .[llm]
```

### 2. Get Your Anthropic API Key

1. Go to https://console.anthropic.com/
2. Create an account or sign in
3. Navigate to API Keys
4. Create a new key
5. Copy the key (starts with `sk-ant-api03-...`)

### 3. Configure Your Environment

Add to your `.env` file:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

### 4. Restart the Command Handler

```bash
pkill -f telegram_command_handler
./scripts/telegram/start_command_handler.sh --background
```

### 5. Update Telegram Commands (Optional)

```bash
python3 scripts/telegram/set_bot_commands.py
```

---

## Usage

### Basic Syntax

```
/ai_patch <file(s)> <task description>
```

- **file(s)**: Path to file(s) to modify, comma-separated for multiple
- **task**: Natural language description of what to change

### Examples

**Single file:**
```
/ai_patch src/pearlalgo/utils/retry.py add exponential backoff with jitter
```

**Multiple files:**
```
/ai_patch src/foo.py,src/bar.py move the helper function from foo to bar
```

**Bug fix:**
```
/ai_patch src/pearlalgo/nq_agent/main.py fix the race condition in signal handling
```

**Add feature:**
```
/ai_patch src/pearlalgo/utils/telegram_alerts.py add a method to format trade summaries
```

**Refactoring:**
```
/ai_patch src/pearlalgo/strategies/nq_breakout.py extract the validation logic into a separate method
```

---

## Applying Patches

### Method 1: Direct Apply (Recommended)

1. Save the `.diff` file from Telegram to your project directory
2. Run:
   ```bash
   git apply patch.diff
   ```

### Method 2: Apply with Review

```bash
# Preview what will change
git apply --stat patch.diff

# Check if it applies cleanly
git apply --check patch.diff

# Apply with verbose output
git apply -v patch.diff
```

### Method 3: Apply as Commit

```bash
# Apply and stage changes
git apply --index patch.diff

# Review staged changes
git diff --cached

# Commit
git commit -m "Applied AI patch: <description>"
```

### Troubleshooting Patches

**Patch doesn't apply cleanly:**
```bash
# Try with more context tolerance
git apply --3way patch.diff

# Or apply what you can
git apply --reject patch.diff
# Then manually fix .rej files
```

**Whitespace issues:**
```bash
git apply --whitespace=fix patch.diff
```

---

## Response Formats

### Small Patches (Inline)

For patches under ~3500 characters, you'll receive the diff inline:

```
✅ Patch Generated

Files: src/pearlalgo/utils/retry.py
Task: add jitter to backoff

```diff
--- a/src/pearlalgo/utils/retry.py
+++ b/src/pearlalgo/utils/retry.py
@@ -10,6 +10,7 @@ def retry():
     # existing code
+    # new code
     pass
```

💡 Apply with: git apply patch.diff
```

### Large Patches (File)

For larger patches, you'll receive a `patch.diff` file attachment that you can download and apply.

---

## Security

### Blocked Paths

The following paths are blocked for security:

| Path | Reason |
|------|--------|
| `data/` | Contains runtime state and signals |
| `logs/` | Contains operational logs |
| `.env` | Contains secrets |
| `ibkr/` | Contains broker configuration |
| `.venv/` | Virtual environment |
| `.git/` | Git internals |
| `*.json` | Config and state files |
| `*.pyc` | Compiled Python |

### Authorization

- Only your authorized chat ID can use `/ai_patch`
- The command handler validates chat ID before processing
- API keys are never logged or transmitted via Telegram

### Path Traversal Protection

- Paths are resolved and validated against the project root
- Attempts to access files outside the project are blocked

---

## Configuration

All configuration is optional. Defaults work well for most use cases.

### Environment Variables

Add to `.env`:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-api03-...

# Optional (with defaults)
ANTHROPIC_MODEL=claude-sonnet-4-20250514
ANTHROPIC_MAX_TOKENS=4096
ANTHROPIC_TIMEOUT=120
```

### Model Selection

| Model | Best For |
|-------|----------|
| `claude-sonnet-4-20250514` | Default, good balance of speed/quality |
| `claude-opus-4-20250514` | Complex refactoring, large codebases |

### Timeout Tuning

For complex tasks or slow connections:
```bash
ANTHROPIC_TIMEOUT=180  # 3 minutes
```

### Token Limits

For larger patches:
```bash
ANTHROPIC_MAX_TOKENS=8192
```

---

## Best Practices

### Writing Effective Tasks

**Be specific:**
```
# Good
/ai_patch src/utils/retry.py add exponential backoff starting at 1s, max 30s, with 10% jitter

# Less good
/ai_patch src/utils/retry.py improve the retry logic
```

**Include context when needed:**
```
/ai_patch src/api/client.py handle rate limit errors (HTTP 429) with automatic retry
```

**Reference existing patterns:**
```
/ai_patch src/new_module.py add logging using the same pattern as telegram_alerts.py
```

### File Selection

**Include related files:**
```
# If changing an interface, include implementations
/ai_patch src/base.py,src/impl.py add a new abstract method and implement it
```

**Keep scope focused:**
```
# Better to do multiple focused patches than one giant one
/ai_patch src/utils/retry.py add jitter
/ai_patch src/utils/retry.py add max_retries parameter
```

### Review Before Applying

Always review the generated patch:
- Check the logic is correct
- Verify it matches your intent
- Test after applying

---

## Troubleshooting

### "AI Patch Not Available"

**Cause:** `anthropic` package not installed

**Fix:**
```bash
pip install -e .[llm]
```

### "API Key Not Configured"

**Cause:** `ANTHROPIC_API_KEY` not set in `.env`

**Fix:**
1. Get key from https://console.anthropic.com/
2. Add to `.env`:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```
3. Restart command handler

### "Blocked Path"

**Cause:** Trying to modify a protected path

**Fix:** Use allowed paths (source files in `src/`, `tests/`, `scripts/`, `docs/`)

### "File Not Found"

**Cause:** Path doesn't exist or typo in path

**Fix:** 
- Check the exact path with `ls` or file explorer
- Paths are relative to project root

### "Claude API Error"

**Cause:** Rate limit, network issue, or API error

**Fix:**
- Wait a moment and retry
- Check your API key is valid
- Check Anthropic status page

### Empty Response

**Cause:** Task unclear or files already satisfy requirement

**Fix:**
- Be more specific about the change needed
- Verify the current state of the file

---

## Cost Considerations

Claude API usage is billed by Anthropic. Typical costs:

| Operation | Approximate Cost |
|-----------|------------------|
| Simple patch (1 file, small) | ~$0.01-0.03 |
| Medium patch (1-2 files) | ~$0.03-0.10 |
| Complex patch (multiple files) | ~$0.10-0.30 |

**Tips to minimize costs:**
- Be specific to reduce back-and-forth
- Use smaller files when possible
- Avoid repeated retries for the same task

---

## Limitations

1. **File size limit:** 100KB per file
2. **No binary files:** Only text files supported
3. **No automatic apply:** You must review and apply patches manually
4. **Single conversation:** No multi-turn refinement (yet)
5. **Blocked paths:** Cannot modify data, logs, env, or secrets

---

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Telegram  │────▶│ Command Handler  │────▶│ Claude API  │
│   (Mobile)  │     │   (Beelink)      │     │ (Anthropic) │
└─────────────┘     └──────────────────┘     └─────────────┘
       │                    │                       │
       │                    ▼                       │
       │           ┌──────────────┐                 │
       │           │  Read Files  │                 │
       │           │  (src/, etc) │                 │
       │           └──────────────┘                 │
       │                    │                       │
       │                    ▼                       ▼
       │           ┌──────────────────────────────────┐
       │           │      Generate Unified Diff       │
       │           └──────────────────────────────────┘
       │                           │
       ▼                           ▼
┌─────────────┐           ┌──────────────┐
│ Receive     │◀──────────│ Send .diff   │
│ Patch       │           │ or inline    │
└─────────────┘           └──────────────┘
       │
       ▼
┌─────────────┐
│ git apply   │
│ patch.diff  │
└─────────────┘
```

---

## Related Documentation

- [TELEGRAM_GUIDE.md](TELEGRAM_GUIDE.md) - Full Telegram integration reference
- [CHEAT_SHEET.md](CHEAT_SHEET.md) - Quick operational reference
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Architecture overview

---

## Changelog

### v1.0.0 (2024-12-30)
- Initial release
- `/ai_patch` command with Claude integration
- Unified diff output (inline or file)
- Path security (blocked paths, traversal protection)
- Authorization via chat ID

