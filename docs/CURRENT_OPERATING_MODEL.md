# Current Operating Model

This is the current source of truth for running PEARL.

## Canonical Structure

- Repo root: `/home/pearlalgo/projects/pearl-algo`
- Live runtime state: `/home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ`
- Repo compatibility path: `data/` is a symlink into `~/var/pearl-algo/state/data`
- Repo logs path: `logs/` is a symlink into `~/var/pearl-algo/logs`
- Web app frontend: `apps/pearl-algo-app/`
- Web app/API wrapper scripts: `scripts/pearlalgo_web_app/`

## Canonical Runtime

- Market data: IBKR Gateway only
- Execution: Tradovate Paper only
- Active strategy bundle: `src/pearlalgo/strategies/composite_intraday/`
- Legacy strategy compatibility namespace: `src/pearlalgo/trading_bots/` remains only as an implementation bridge while the canonical strategy wrappers are simplified
- Canonical config: `config/live/tradovate_paper.yaml`
- Legacy overlay: `config/accounts/tradovate_paper.yaml` is retained only for migration compatibility

## Safety Baseline

- Current state should be checked before any restart or re-arm:
  - `./pearl.sh quick`
  - `python3 scripts/ops/audit_runtime_paths.py`
- Trading is safe only when:
  - `positions=[]`
  - `execution.armed=false` until you intentionally re-arm
- No strategy or execution changes should be mixed with web app/UI work.

## Core Commands

```bash
cd ~/projects/pearl-algo
./pearl.sh quick
./pearl.sh status
./pearl.sh start
./pearl.sh stop
./pearl.sh restart
python3 scripts/ops/audit_runtime_paths.py
```

## What Is Archived

The following are historical context, not operational truth:

- `docs/archive/2026-04-stabilization/`
- `docs/archive/`
- `scripts/_archived/`
- `data/archive/`

If a doc conflicts with this file, `START_HERE.md`, or `PATH_TRUTH_TABLE.md`, treat the archived doc as historical only.
