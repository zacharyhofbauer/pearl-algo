# Compatibility Surfaces

This file is the single place to record intentionally retained compatibility
surfaces. If a path or behavior remains only to avoid breaking callers, list it
here rather than repeating the same caveat throughout the repo.

## Live compatibility surfaces

- `scripts/pearlalgo_web_app/`
  Compatibility wrappers around `src/pearlalgo/api/server.py`. These are still
  invoked by `pearl.sh`, systemd units, lifecycle scripts, and API tests.
- `src/pearlalgo/trading_bots/`
  Legacy strategy namespace retained while canonical strategy entrypoints live
  under `src/pearlalgo/strategies/`.
- `NEXT_PUBLIC_API_KEY` and websocket `?api_key=...`
  Legacy frontend auth fallbacks retained while the preferred names remain
  `NEXT_PUBLIC_READONLY_API_KEY` and the websocket auth message.
- `src/pearlalgo/market_agent/openclaw_guard.py`
  Retained pending manual review of external/runtime integrations.

## Removed historical material

Historical migration notes and archived scripts/docs have been removed from the
active repo surface. Use git history for prior rollout context instead of
pointing current docs at deleted archive paths.
