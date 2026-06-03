# progress.md

## 2026-06-02 — Pivot to manual TradingView-alert model (PR #57)

Repo reframed from the automated MNQ bot to a **manual discretionary** toolkit.

- Active: `pine/mnq_rth_long_bias.pine` (RTH-only, long-bias, MNQ; emits alert JSON), `alerts/` (TradingView→Discord), `docs/MANUAL_PIVOT.md` (validation gate), `docs/JOURNAL.md`.
- Automated bot is DORMANT (`execution.armed=false`), preserved at tag `legacy/automated-mnq-2026-06-02` (parked after −2,026 pts / 717 trades). Re-arm via `docs/legacy/README.md`.
- Prop firm **MFF**, instrument **MNQ**. NOT validated — the Pine signal family is the same one the bot lost on; the new variable is operator discretion. Clear the gate (≥30 trades, +expectancy net of fees, max DD inside MFF trailing-DD) BEFORE funded capital.
- Open: fill exact MFF tier rules into `docs/MANUAL_PIVOT.md`; run Strategy Tester + paper-trade the alert loop.

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
