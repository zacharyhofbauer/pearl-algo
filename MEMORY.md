# MEMORY.md

Curated repo knowledge promoted from daily work logs.

## Canonical Runtime

- `./pearl.sh` is the top-level operator entrypoint.
- `config/live/tradovate_paper.yaml` is the canonical live runtime config.
- The market-agent runtime is singleton-only; `--market` selects state/log namespace but does not enable concurrent agents.
- IBKR is data-only; Tradovate Paper is the execution source of truth.
- Runtime notifications are disabled/no-op; do not build new live paths that depend on Telegram delivery.

## State And API

- `signals.jsonl` is append-only and remains the lightweight signal history / recovery source.
- `trades.db` is the analytics/query layer, not the recovery source of truth.
- Hot API signal endpoints should reuse `pearlalgo.api.data_layer` readers instead of hand-rolled `signals.jsonl` scans.

## Frontend

- The canonical dashboard lives in `apps/pearl-algo-app/`.
- `src/pearlalgo/api/server.py` is the FastAPI backend for the chart/dashboard.
- Browser dashboard is canonical; Telegram screenshot and mini-app guidance is historical only.

## Compatibility Surfaces

- `src/pearlalgo/trading_bots/` remains a legacy bridge namespace.
- `scripts/pearlalgo_web_app/` remains a wrapper layer around the API/web stack.
- Legacy Telegram constructor kwargs are still accepted in some service constructors, but they are ignored.
