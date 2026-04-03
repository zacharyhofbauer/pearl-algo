# AGENTS.md

Repo-local operating memory for PEARL Algo agents.

## Architecture Overview

- Operator entrypoint: `./pearl.sh`
  Why: this is the canonical control surface for the live stack.
- Runtime topology: singleton market-agent process via `python -m pearlalgo.market_agent.main`
  Why: the runtime takes a global lock at `/tmp/pearlalgo-agent.lock`; `--market` selects state/log namespace, not concurrent agents.
- Market data: IBKR gateway only
  Why: IBKR execution is intentionally inactive on the canonical live path.
- Execution: Tradovate Paper via `src/pearlalgo/execution/tradovate/`
  Why: Tradovate Paper is the source of truth for live trades and fills.
- Canonical live config: `config/live/tradovate_paper.yaml`
  Why: compatibility overlays exist, but live edits belong in the canonical runtime config.
- Canonical frontend/API: `apps/pearl-algo-app/` and `src/pearlalgo/api/server.py`
  Why: browser dashboard plus FastAPI are the active operator-facing surfaces.

## Banned Patterns

- Do not re-enable Telegram runtime notifications.
  Why: runtime delivery was removed; `notification_queue.py` is a no-op compatibility contract only.
- Do not assume concurrent multi-market agents are supported.
  Why: singleton locking makes that behavior incorrect even if scripts still accept `--market`.
- Do not add new live trading logic under `src/pearlalgo/trading_bots/` or wrapper scripts.
  Why: those are compatibility surfaces; new canonical strategy work belongs under `src/pearlalgo/strategies/`.
- Do not change execution arming, guardrails, or position-size limits without explicit approval.
  Why: this repo controls a 24/7 trading system and these values are safety-critical.
- Do not write state files through ad hoc helpers when shared readers/writers already exist.
  Why: `state_manager`, `state_reader`, `state_io`, and `api.data_layer` encode locking, caching, and tail-read behavior the rest of the system depends on.

## State-Management Quirks

- `data/` and `logs/` in the repo are compatibility symlinks into `/home/pearlalgo/var/pearl-algo/`.
  Why: local paths in the checkout are not the canonical live storage locations.
- `signals.jsonl` is append-only and remains the recovery/tail-read source of truth; `trades.db` is the query layer.
  Why: SQLite can lag or be rebuilt, while JSONL is used for recovery and lightweight readers.
- API signal-heavy paths should reuse `pearlalgo.api.data_layer`.
  Why: shared TTL caching and paginated/tail readers avoid repeated ad hoc scans of `signals.jsonl`.
- Web/API/operator actions should use existing state and flag-file flows.
  Why: direct side writes create race conditions with the single writer in the market agent.

## Deployment Constraints

- Single active account: Tradovate Paper.
  Why: the current operating model is intentionally narrow and conservative.
- Required live services: IBKR Gateway, singleton market agent, FastAPI server, Next.js web app.
  Why: systemd and `./pearl.sh` are structured around this stack.
- Validate before closing work: compile/tests/doc checks as appropriate.
  Why: untested changes are not done for this repo.
