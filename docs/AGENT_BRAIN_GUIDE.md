# Agent “Brain” Guide (How This System Thinks)

This repo has two different “brains”:

- **Rule-based brain**: deterministic strategy code that scans, scores, and emits signals.
- **Learning brain**: lightweight online learning (bandits) + optional ML filter + optional AI monitor suggestions.

This guide shows the wiring so you can modify it confidently.

## Architecture in 60 seconds

### Data → signals

- **Entrypoint**: `src/pearlalgo/nq_agent/main.py`
- **Service loop (the “agent”)**: `src/pearlalgo/nq_agent/service.py`
- **Strategy wrapper**: `src/pearlalgo/strategies/nq_intraday/strategy.py`
- **Pattern/indicator scan**: `src/pearlalgo/strategies/nq_intraday/scanner.py`
- **Filtering + sizing + observability**: `src/pearlalgo/strategies/nq_intraday/signal_generator.py`
- **In-trade management (virtual trailing/BE)**: `src/pearlalgo/strategies/nq_intraday/trade_manager.py`

### Signals → tracking (so it can learn)

- **Persistence / signals.jsonl**: `src/pearlalgo/nq_agent/state_manager.py`
- **PnL + win/loss + metrics**: `src/pearlalgo/nq_agent/performance_tracker.py`
- **Virtual PnL engine (TP/SL touch logic)**: `NQAgentService._update_virtual_trade_exits()` in `src/pearlalgo/nq_agent/service.py`

## Where the “brain” lives

### 1) Fast online learning (Bandit)

- **Policy**: `src/pearlalgo/learning/bandit_policy.py`
- **State on disk**: `data/agent_state/<MARKET>/policy_state.json`
- **What it learns**: per-`signal_type` win/loss (Beta distribution) + avg pnl.

How it’s used:
- In **shadow** mode, it annotates signals (for transparency) but does not block execution.
- In **live** mode, it can gate execution (when execution is enabled/armed).

### 2) Contextual learning (optional)

- **Policy**: `src/pearlalgo/learning/contextual_bandit.py`
- **Goal**: learn “this signal works in *this* regime/session, not everywhere”.

### 3) ML filter (optional)

- **Filter**: `src/pearlalgo/learning/ml_signal_filter.py`
- **Features**: `src/pearlalgo/learning/feature_engineer.py`
- **Usage**: typically start in “shadow” mode, then switch to live blocking once it proves lift.

### 4) AI Monitor (optional)

- **Goal**: analyze outcomes and *suggest* bounded config changes (optionally auto-apply).

## Config that matters (mental model)

You mainly touch:
- `config/config.yaml`
- `src/pearlalgo/strategies/nq_intraday/config.py` (strategy config loader + enable/disable semantics)

Important knobs:
- **Signal families enabled/disabled**: `strategy.enabled_signals`, `strategy.disabled_signals`
- **Signal quality thresholds**: `signals.min_confidence`, `signals.min_risk_reward`, `signals.quality_score.*`
- **Risk shaping**: `risk.signal_type_size_multipliers`, `risk.signal_type_max_contracts`

## Practical: “how do I make it have a brain of its own?”

1. **Make sure outcomes are being tracked**
   - Virtual PnL should be enabled (`virtual_pnl.enabled: true`) so exits record wins/losses.
2. **Inspect what it learned**
   - Look at `data/agent_state/<MARKET>/policy_state.json` for per-type win rate / samples / avg pnl.
3. **Let learning influence behavior**
   - Switch bandit from shadow → live (and tune threshold/explore rate) when you’re ready.
4. **Graduate to context + ML**
   - Turn on contextual bandit for regime/session-aware gating.
   - Train and enable the ML filter if you want feature-driven selection beyond heuristics.

