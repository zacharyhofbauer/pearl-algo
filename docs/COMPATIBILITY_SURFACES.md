# Compatibility Surfaces

Retained bridges, wrappers, and fallback paths that still exist in `pearl-algo`, but are **not** the preferred place for new work.

## Canonical live path

For the current operating model, use:
- `docs/START_HERE.md`
- `docs/PATH_TRUTH_TABLE.md`
- `config/live/tradovate_paper.yaml`
- `src/pearlalgo/strategies/composite_intraday/`
- `src/pearlalgo/execution/tradovate/`
- `./pearl.sh`

## Retained compatibility surfaces

### 1. Legacy strategy bridge: `pearlalgo.trading_bots`

The repo still contains legacy strategy implementation code under `src/pearlalgo/trading_bots/`.

Current reality:
- parts of `strategies/composite_intraday` still delegate into this namespace
- this keeps the live system working
- it is technical debt, not the target architecture

Rule:
- do not add new strategy entrypoints here
- move logic outward into `strategies/composite_intraday` when refactoring

### 2. API compatibility wrappers in `pearlalgo.api.server`

`src/pearlalgo/api/server.py` still exposes wrapper/helper functions that forward into extracted modules such as:
- `pearlalgo.api.tradovate_helpers`
- `pearlalgo.api.data_layer`

These wrappers exist so older call sites and tests keep a stable contract while implementation is being peeled out of the monolith.

Rule:
- prefer adding new logic in the extracted helper modules
- keep wrapper signatures stable unless callers are updated in the same change

### 3. Notification compatibility surface

`src/pearlalgo/market_agent/notification_queue.py` is retained as a no-op compatibility layer.

Rule:
- do not build new runtime features on top of it
- treat it as a stable shim for old callers only

### 4. Fallback state readers / retained file contracts

Some runtime views still support legacy state-file patterns so dashboards, operator scripts, and recovery flows stay intact during cleanup.

Examples include:
- `performance.json`
- `signals.jsonl`
- `state.json`
- persisted Tradovate fill/state snapshots under `data/agent_state/<MARKET>/`

Rule:
- preserve these contracts unless you are intentionally migrating every dependent consumer
- prefer additive migrations with validation over silent path swaps

## Working rule of thumb

If a change touches one of these compatibility surfaces, ask:
1. Is this required to preserve an existing contract?
2. If not, should the change go in the canonical path instead?

Default answer: **put new work in the canonical path, not the compatibility layer.**
