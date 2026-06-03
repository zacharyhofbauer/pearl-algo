"""MNQ strategy validation framework.

Pure, engine-agnostic primitives that consume a per-trade net-P&L series (in
index points) or an equity curve produced by scripts/ops/backtest_config.py.
Built to answer, honestly: does a strategy have a robust edge that survives
realistic costs AND the prop-firm trailing drawdown — and at what size?

See ~/.claude/plans/im-starting-to-think-curious-sketch.md for the gate ladder.
"""
