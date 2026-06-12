#!/usr/bin/env python3
"""Path-C pre-registration conditioning census (NO trade outcomes).

Computes, over the dev window only (2025-10-26 .. 2026-04-19, ET):
  - per-session overnight gap = first RTH 5m bar OPEN minus prior trading
    date's RTH close (last bar with ET time in [09:30, 16:00))
  - ATR_d(14): Wilder ATR over daily aggregates (ET calendar date, full ETH
    range), using only days strictly before the session (shift by one day);
    valid only once 14 complete prior daily aggregates exist (the archive's
    first, possibly partial, calendar day is excluded)
  - contract-roll candidates: |gap| outliers (> 5 x MAD) — quarterly roll
    weeks are where an unadjusted spliced series embeds the calendar spread
  - expected qualifying-session counts for trials 16/17/18

This script reads ONLY conditioning variables (gap sizes, ATR, first-bar
close vs prior close). It simulates no entries, exits, or P&L — running it
before the trials is the pre-registered, outcome-blind n-disclosure step.
See docs/audits/validation-trial-ledger.md (Path C) and
docs/plans/2026-06-12-001-feat-gap-family-validation-pine-honesty-plan.md.
"""
from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
DB = Path(__file__).resolve().parents[2] / "data" / "candles.db"
DEV_START = "2025-10-26"
DEV_END = "2026-04-19"  # inclusive
RTH_OPEN = dtime(9, 30)
RTH_CLOSE = dtime(16, 0)
COST_FLOOR_PTS = 5.0
SMALL_CEIL = 0.30
LARGE_FLOOR = 0.70
ATR_N = 14


def et(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=UTC).astimezone(ET)


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT ts, open, high, low, close FROM candles "
        "WHERE symbol='MNQ' AND tf='5m' ORDER BY ts"
    ).fetchall()
    con.close()

    # Group by ET calendar date (full ETH range per date).
    days: dict[str, list[tuple]] = {}
    for r in rows:
        days.setdefault(et(r[0]).strftime("%Y-%m-%d"), []).append(r)
    dates = sorted(days)

    # Daily aggregates; drop the first (possibly partial) archive day.
    daily = []  # (date, high, low, close)
    for d in dates[1:]:
        bars = days[d]
        daily.append((d, max(b[2] for b in bars), min(b[3] for b in bars), bars[-1][4]))

    # Wilder ATR over daily aggregates; atr_for[date] = ATR as of the PRIOR day
    # (no lookahead), valid only after ATR_N complete prior days.
    atr_for: dict[str, float] = {}
    atr = None
    trs: list[float] = []
    for i in range(1, len(daily)):
        d, hi, lo, _cl = daily[i]
        prev_close = daily[i - 1][3]
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        if atr is None:
            trs.append(tr)
            if len(trs) == ATR_N:
                atr = sum(trs) / ATR_N
        else:
            atr = (atr * (ATR_N - 1) + tr) / ATR_N
        if atr is not None and i + 1 < len(daily):
            atr_for[daily[i + 1][0]] = atr  # valid for the NEXT day

    # Per-session: prior RTH close and first RTH bar.
    def rth_bars(d: str):
        return [b for b in days[d] if RTH_OPEN <= et(b[0]).time() < RTH_CLOSE]

    sessions = []  # dicts of conditioning vars
    rth_dates = [d for d in dates if rth_bars(d)]
    for i in range(1, len(rth_dates)):
        d = rth_dates[i]
        if not (DEV_START <= d <= DEV_END):
            continue
        prior = rth_bars(rth_dates[i - 1])
        cur = rth_bars(d)
        prior_close = prior[-1][4]
        first = cur[0]
        gap = first[1] - prior_close  # first RTH bar OPEN - prior RTH close
        remaining = abs(prior_close - first[4])  # at first-bar CLOSE
        pre_filled = (gap > 0 and first[4] <= prior_close) or (
            gap < 0 and first[4] >= prior_close
        )
        sessions.append(
            dict(date=d, gap=gap, atr=atr_for.get(d), remaining=remaining,
                 pre_filled=pre_filled)
        )

    gaps = [abs(s["gap"]) for s in sessions]
    med = statistics.median(gaps)
    mad = statistics.median([abs(g - med) for g in gaps])
    roll_candidates = [s for s in sessions if abs(s["gap"]) > med + 5 * (mad or 1)]

    print(f"dev sessions with RTH bars: {len(sessions)}")
    print(f"|gap| pts: median={med:.1f} q1={statistics.quantiles(gaps, n=4)[0]:.1f} "
          f"q3={statistics.quantiles(gaps, n=4)[2]:.1f} max={max(gaps):.1f}")
    atrs = [s["atr"] for s in sessions if s["atr"]]
    print(f"ATR_d(14) pts: median={statistics.median(atrs):.1f} "
          f"min={min(atrs):.1f} max={max(atrs):.1f}; "
          f"sessions without valid ATR_d: {sum(1 for s in sessions if not s['atr'])}")
    print(f"\nroll candidates (|gap| > median + 5*MAD = {med + 5 * (mad or 1):.1f} pts):")
    for s in roll_candidates:
        print(f"  {s['date']}  gap={s['gap']:+.1f}  ATR_d={s['atr'] or float('nan'):.1f}")

    # Roll-splice exclusion: first sessions on the new contract after the Dec/Mar
    # expirations (IBKR continuous splices at expiry) — prior close and open come
    # from different contracts, so the "gap" embeds the calendar spread.
    ROLL_EXCLUDE = {"2025-12-22", "2026-03-23"}
    for d in ROLL_EXCLUDE:
        s = next((x for x in sessions if x["date"] == d), None)
        print(f"\nroll-splice session {d}: "
              + (f"gap={s['gap']:+.1f} ATR_d={s['atr'] or float('nan'):.1f}" if s else "no RTH session"))

    kept = [s for s in sessions if s["date"] not in ROLL_EXCLUDE]
    valid = [s for s in kept if s["atr"]]
    # Trial 17's condition uses no ATR -> no ATR-warmup gate (registered design).
    t17 = [s for s in kept if abs(s["gap"]) >= COST_FLOOR_PTS]
    t16 = [s for s in valid if COST_FLOOR_PTS <= abs(s["gap"]) <= SMALL_CEIL * s["atr"]]
    t18 = [s for s in valid if abs(s["gap"]) >= LARGE_FLOOR * s["atr"]]
    t_fade_open = [s for s in t17 if not s["pre_filled"] and s["remaining"] >= COST_FLOOR_PTS]
    t16_open = [s for s in t16 if not s["pre_filled"] and s["remaining"] >= COST_FLOOR_PTS]
    print(f"\nexpected n (after roll exclusion):")
    print(f"  trial 16 gap_fade_small  condition-met={len(t16)}  tradable-at-first-bar-close={len(t16_open)}")
    print(f"  trial 17 gap_fade_all (no ATR gate)  condition-met={len(t17)}  tradable-at-first-bar-close={len(t_fade_open)}")
    print(f"  trial 18 gap_continue_large  condition-met={len(t18)}")
    print(f"  pre-filled-by-first-bar-close skips (within trial 17 set): "
          f"{sum(1 for s in t17 if s['pre_filled'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
