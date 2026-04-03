# progress.md

## Current Objective

Align the repo with the approved 2026-04-03 follow-up plan: singleton runtime truth, no-op notification contract completion, repo-local memory bootstrap, post-Telegram doc cleanup, and shared signal-reader reuse in hot API paths.

## Completed Tasks

- Fixed the real `NotificationQueue` contract gap by adding `enqueue_data_quality_alert()`.
- Refactored hot API signal consumers to reuse the shared paginated/tail reader path.
- Added focused tests for the real default notification queue path and cursor-based signal reads.
- Began canonical doc cleanup for singleton runtime and post-Telegram guidance.
- Began repo-local memory bootstrap (`AGENTS.md`, `SOUL.md`, `MEMORY.md`, `USER.md`, `HALLUCINATE.md`, daily memory log).

## Last Session Thread Link

Unavailable from repo-local context. Record the thread URL manually when working from a chat surface that exposes one.

## Discovered Gotchas

- The worktree can be dirty; do not revert unrelated changes.
- `--market` still exists in scripts, but the Python runtime is singleton-locked.
- Telegram runtime modules are gone, but some compatibility kwargs and historical filenames remain.
- `signals.jsonl` hot paths drift easily if callers bypass `pearlalgo.api.data_layer`.
