#!/usr/bin/env python3
"""Trial 19/20 — dev-window validation of the hourly_defender (4h regime / 1h exec) candidate.

Drives the OFFICIAL backtest engine (scripts/ops/backtest_config.run_backtest — same exit
simulation, slippage, commission, and held-out guard as every prior ledger trial) on the
DEV WINDOW ONLY (2025-10-26 → 2026-04-19). The held-out slice (2026-04-20+) is never touched
(allow_held_out stays False; the engine clamps anyway).

Two pre-registered trials (docs/audits/validation-trial-ledger.md, Path D):
  19 — hourly_defender LONG-ONLY  (primary; matches the 922-trade long bias)
  20 — hourly_defender TWO-SIDED  (allow_shorts=true; the variant now default-on in the Pine)

Two-sided is run via a thin wrapper that forces vparams.allow_shorts=True, so the official
engine is used unchanged (no edits to the candidate or the runner).

For each trial: Tier-0 cost-viability (pearlalgo.validation.stats.tier0_verdict). On any Tier-0
PASS, the split-half Tier-1 regime-stability check (H1 2025-10-26→2026-01-22 / H2
2026-01-23→2026-04-19) is run.

Reproduce:  .venv/bin/python scripts/ops/validate_hourly_2026_06_19.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime as dt, timedelta as td
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_config import run_backtest  # noqa: E402  (sibling script in scripts/ops/)
from pearlalgo.validation.stats import tier0_verdict  # noqa: E402
from pearlalgo.validation.strategies.signal_fns import hourly_defender_signals  # noqa: E402

ET = ZoneInfo("America/New_York")
CFG = Path("config/live/tradovate_paper.yaml")


def _ts_from(d: str) -> int:
    return int(dt.strptime(d, "%Y-%m-%d").replace(tzinfo=ET).timestamp())


def _ts_to(d: str) -> int:  # inclusive end-of-ET-day (matches the CLI's --end semantics)
    return int((dt.strptime(d, "%Y-%m-%d").replace(tzinfo=ET) + td(days=1)).timestamp()) - 1


def _two_sided(df, config=None, current_time=None):
    cfg = dict(config or {})
    vp = dict(cfg.get("vparams", {}))
    vp["allow_shorts"] = True
    cfg["vparams"] = vp
    return hourly_defender_signals(df, config=cfg, current_time=current_time)


def _run(fn, start: str, end: str) -> dict:
    return run_backtest(
        CFG, symbol="MNQ", tf="5m", warmup_bars=120, max_hold_minutes=180,
        slippage_points=0.25, commission_points=1.0,
        ts_from=_ts_from(start), ts_to=_ts_to(end),
        strategy_fn=fn, strategy_name="hourly_defender", allow_held_out=False,
    )


def _summ(r: dict) -> dict:
    if "error" in r:
        return {"error": r["error"]}
    npt = r.get("net_points_per_trade") or []
    v = tier0_verdict(npt) if npt else {"verdict": "KILL", "reason": "no trades produced", "undersized": True}
    return {
        "entries": r.get("entries"),
        "exp_pt": r.get("expectancy_points_per_trade"),
        "win_rate": r.get("win_rate"),
        "max_dd_pt": r.get("max_drawdown_points"),
        "tier0": v["verdict"],
        "reason": v["reason"],
        "undersized": v.get("undersized"),
    }


DEV = ("2025-10-26", "2026-04-19")
H1 = ("2025-10-26", "2026-01-22")
H2 = ("2026-01-23", "2026-04-19")
TRIALS = [("trial19_long_only", hourly_defender_signals), ("trial20_two_sided", _two_sided)]


def main() -> int:
    out: dict = {}
    for name, fn in TRIALS:
        s = _summ(_run(fn, *DEV))
        out[name] = {"window": "dev 2025-10-26->2026-04-19", **s}
        if "error" in s:
            print(f"\n{name}: ERROR {s['error']}")
            continue
        print(f"\n{name}: n={s['entries']} exp={s['exp_pt']:+.2f} pt  win={s['win_rate']}  "
              f"DD={s['max_dd_pt']}  ->  TIER-0 {s['tier0']}  ({s['reason']})")
        if s["tier0"] == "PASS":
            for hn, (a, b) in (("H1", H1), ("H2", H2)):
                hs = _summ(_run(fn, a, b))
                out[name][hn] = hs
                print(f"   {hn} {a}->{b}: n={hs.get('entries')} exp={hs.get('exp_pt')}")
    art = Path("docs/audits/2026-06-19-hourly_defender_validation.json")
    art.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nsaved {art}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
