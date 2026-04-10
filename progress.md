# progress.md

## Current State (2026-04-07)

Repo is in a clean, consolidated state after full Claude Code config cleanup and documentation audit.

## Recent Completed Work

- Full `~/.claude/` cleanup: removed 5 stale project directories (~85 MB), consolidated to single active project context
- Removed duplicate `MEMORY.md` and `memory/` from project root (auto-memory at `~/.claude/` is canonical)
- Removed 5 duplicate `HALLUCINATE.md` files (kept `docs/HALLUCINATE.md` only)
- Fixed color token mismatch in `DESIGN_SYSTEM.md` to match actual `tokens.css` values
- Removed stale `PEARLALGO_CONFIG_PATH` from `.env` (pointed to non-existent workspace)
- Removed orphaned `static/dashboard_v2.html` and `docs/legacy/` (Telegram artifacts)
- Fixed stale doc references in `env.example`
- Removed stale `htmlcov/`, `.coverage`

## Known State

- `config/config.yaml` and `config/base.yaml` both exist and are both used (config loader cascade)
- `--market` flag in pearl.sh is effectively a no-op (singleton runtime)
- Telegram runtime is fully removed; some compatibility kwargs remain in service constructors
- `signals.jsonl` is recovery source of truth; `trades.db` is analytics only

## Discovered Gotchas

- The worktree can be dirty; do not revert unrelated changes
- `signals.jsonl` hot paths drift easily if callers bypass `pearlalgo.api.data_layer`
