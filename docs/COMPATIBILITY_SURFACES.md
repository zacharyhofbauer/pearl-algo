# Compatibility Surfaces

This file is the single place to record intentionally retained compatibility
surfaces. If a path or behavior remains only to avoid breaking callers, list it
here rather than repeating the same caveat throughout the repo.

Rule of thumb: if it is not part of the operating model in
`docs/START_HERE.md`, it should either be removed or recorded here with a
reason it still exists.

## Live compatibility surfaces

- `./pearlalgo.sh`
  Compatibility alias for `./pearl.sh`. Keep only while operators or old docs
  still call the old name. Do not document it as the primary entrypoint.
- `scripts/pearlalgo_web_app/`
  Compatibility wrappers around `src/pearlalgo/api/server.py`. These are still
  invoked by `pearl.sh`, systemd units, lifecycle scripts, and API tests.
- `src/pearlalgo/trading_bots/`
  Legacy strategy namespace retained while canonical strategy entrypoints live
  under `src/pearlalgo/strategies/`. No new strategy entrypoints should be
  added here.
- `src/pearlalgo/strategies/composite_intraday/pinescript_core.py`
- `src/pearlalgo/strategies/composite_intraday/smc.py`
- `src/pearlalgo/strategies/composite_intraday/orb.py`
- `src/pearlalgo/strategies/composite_intraday/vwap_2sd.py`
  Canonical strategy-facing wrappers that still delegate to legacy strategy
  implementation details. `smc.py`, `orb.py`, and `vwap_2sd.py` are currently
  orphan-allowlisted, so they are good removal candidates once external callers
  are confirmed absent.
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
- `src/pearlalgo/market_agent/openclaw_guard.py`
  Retained pending manual review of external/runtime integrations.

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
