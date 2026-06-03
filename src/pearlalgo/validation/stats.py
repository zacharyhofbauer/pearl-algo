"""Validation statistics: bootstrap CIs, the Tier-0 gate, Sharpe, deflated Sharpe.

Pure functions over a per-trade net-P&L series (index points) or per-period
returns. No engine/data deps so they're unit-testable in isolation.

Tier-0 gate (from the plan): a strategy is KILLED if net expectancy <= 0, or if
0 < expectancy < min_expectancy and the 95% bootstrap CI of the mean crosses
zero. A sample below min_trades is flagged UNDERSIZED (a caveat, not a pass).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Sequence

import numpy as np


def bootstrap_mean_ci(
    samples: Sequence[float],
    *,
    n_boot: int = 10_000,
    ci: float = 0.95,
    seed: int = 12345,
) -> Dict[str, Any]:
    """Percentile bootstrap CI for the mean of ``samples`` (e.g. net pts/trade)."""
    a = np.asarray(list(samples), dtype=float)
    n = int(a.size)
    if n == 0:
        return {"n": 0, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "ci": ci, "n_boot": n_boot}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = a[idx].mean(axis=1)
    alpha = (1.0 - ci) / 2.0
    return {
        "n": n,
        "mean": float(a.mean()),
        "std": float(a.std(ddof=1)) if n > 1 else 0.0,
        "ci_low": float(np.quantile(means, alpha)),
        "ci_high": float(np.quantile(means, 1.0 - alpha)),
        "ci": ci,
        "n_boot": n_boot,
    }


def tier0_verdict(
    net_points_per_trade: Sequence[float],
    *,
    min_expectancy: float = 1.0,
    min_trades: int = 100,
    n_boot: int = 10_000,
    seed: int = 12345,
) -> Dict[str, Any]:
    """Apply the Tier-0 cost-viability gate to a NET (post-commission) pnl series."""
    boot = bootstrap_mean_ci(net_points_per_trade, n_boot=n_boot, seed=seed)
    mean, lo, hi, n = boot["mean"], boot["ci_low"], boot["ci_high"], boot["n"]
    if n == 0:
        verdict, reason = "KILL", "no trades produced"
    elif mean <= 0:
        verdict, reason = "KILL", f"net expectancy {mean:+.3f} pt/trade <= 0"
    elif mean < min_expectancy and lo <= 0:
        verdict = "KILL"
        reason = (
            f"net expectancy {mean:+.3f} pt in (0, {min_expectancy}) and the 95% "
            f"bootstrap CI low {lo:+.3f} crosses zero (indistinguishable from break-even)"
        )
    else:
        verdict = "PASS"
        reason = f"net expectancy {mean:+.3f} pt/trade, 95% CI [{lo:+.3f}, {hi:+.3f}]"
    return {
        "verdict": verdict,
        "reason": reason,
        "expectancy_net_pts": round(mean, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "n_trades": n,
        "undersized": n < min_trades,
        "min_trades": min_trades,
    }


def per_period_sharpe(period_returns: Sequence[float], *, periods_per_year: int = 252) -> float:
    """Annualized Sharpe from PER-PERIOD returns (e.g. daily equity returns).

    NOTE: do NOT feed per-trade P&L here — that was the engine's Sharpe bug.
    Resample the equity curve to a fixed period (daily) first.
    """
    r = np.asarray(list(period_returns), dtype=float)
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd * math.sqrt(periods_per_year))


def deflated_sharpe_ratio(
    observed_sr: float,
    *,
    n_trials: int,
    sr_variance_across_trials: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Returns P(true SR > 0) after correcting ``observed_sr`` for (a) the number
    of independent trials and (b) non-normal returns. For Tier 3. ``n_trials``
    must include EVERY parameter set tried (seed from the trial ledger).
    """
    from scipy.stats import norm  # scipy ships with scikit-learn (already installed)

    n_trials = max(1, int(n_trials))
    emc = 0.5772156649015329  # Euler-Mascheroni
    # Expected maximum Sharpe across n_trials independent null strategies.
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    sr0 = math.sqrt(max(sr_variance_across_trials, 0.0)) * ((1.0 - emc) * z1 + emc * z2)
    denom = math.sqrt(max(1.0 - skew * observed_sr + (kurtosis - 1.0) / 4.0 * observed_sr ** 2, 1e-12))
    num = (observed_sr - sr0) * math.sqrt(max(n_obs - 1, 1))
    return float(norm.cdf(num / denom))
