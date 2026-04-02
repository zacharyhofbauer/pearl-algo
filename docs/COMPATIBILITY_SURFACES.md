# Compatibility Surfaces

This file is the single place to record intentionally retained compatibility
surfaces. If a path or behavior remains only to avoid breaking callers, list it
here rather than repeating the same caveat throughout the repo.

Rule of thumb: if it is not part of the operating model in
`docs/START_HERE.md`, it should either be removed or recorded here with a
reason it still exists.

## Live compatibility surfaces

- `scripts/pearlalgo_web_app/`
  Compatibility wrappers around `src/pearlalgo/api/server.py`. These are still
  invoked by `pearl.sh`, systemd units, lifecycle scripts, and API tests.
- `src/pearlalgo/trading_bots/`
  Legacy strategy namespace retained while canonical strategy entrypoints live
  under `src/pearlalgo/strategies/`. No new strategy entrypoints should be
  added here.
- `src/pearlalgo/strategies/composite_intraday/pinescript_core.py`
  Canonical strategy-facing wrapper that still delegates to legacy strategy
  implementation details.
- `src/pearlalgo/config/migration.py`
- legacy overlay/config fallbacks in `src/pearlalgo/config/config_file.py`,
  `src/pearlalgo/config/config_loader.py`, and `src/pearlalgo/market_agent/main.py`
  Compatibility layer for older config shapes such as `pearl_bot_auto` and
  legacy `trading_circuit_breaker` blocks. New runtime config should be authored
  directly in `config/live/tradovate_paper.yaml` shape.
- `NEXT_PUBLIC_API_KEY` and websocket `?api_key=...`
  Legacy frontend auth fallbacks retained while the preferred names remain
  `NEXT_PUBLIC_READONLY_API_KEY` and the websocket auth message.
- `src/pearlalgo/utils/telegram_alerts.py`
  Backward-compatible re-export surface. New imports should use
  `pearlalgo.notifications.*`.

## Removal standard

A compatibility surface is safe to delete only after all of the following are
true:

- the canonical replacement is documented and in use
- tests/imports/scripts no longer reference the old path or behavior
- operator scripts and systemd units no longer depend on it
- docs no longer point to it as an active path

## Removed historical material

Historical migration notes and archived scripts/docs have been removed from the
active repo surface. Use git history for prior rollout context instead of
pointing current docs at deleted archive paths.

Removed in the April 2, 2026 cleanup pass:
- deprecated top-level launcher shim
- three unused composite-intraday bridge wrapper modules
- the unused OpenClaw guard module
