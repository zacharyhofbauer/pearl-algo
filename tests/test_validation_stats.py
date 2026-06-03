"""Tests for pearlalgo.validation.stats — the Tier-0 gate + bootstrap CI."""
from __future__ import annotations

import numpy as np
import pytest

from pearlalgo.validation.stats import (
    bootstrap_mean_ci,
    per_period_sharpe,
    tier0_verdict,
)


def _series(mean: float, sd: float, n: int = 300, seed: int = 7) -> list[float]:
    return list(np.random.default_rng(seed).normal(mean, sd, n))


def test_tier0_kills_clearly_negative():
    v = tier0_verdict(_series(-5.0, 40))
    assert v["verdict"] == "KILL"
    assert v["expectancy_net_pts"] < 0


def test_tier0_passes_solid_positive():
    v = tier0_verdict(_series(2.0, 8))
    assert v["verdict"] == "PASS"
    assert v["ci95"][0] > 0  # CI low above zero


def test_tier0_kills_marginal_with_ci_crossing_zero():
    # Deterministic: recenter to an EXACT +0.5 mean with wide spread so the
    # 95% bootstrap CI of the mean crosses zero -> KILL via the marginal branch.
    s = np.random.default_rng(0).normal(0.0, 30.0, 120)
    s = list(s - s.mean() + 0.5)
    v = tier0_verdict(s, min_expectancy=1.0)
    assert 0 < v["expectancy_net_pts"] < 1.0
    assert v["verdict"] == "KILL"
    assert v["ci95"][0] <= 0 <= v["ci95"][1]


def test_tier0_flags_undersized_sample():
    v = tier0_verdict(_series(-5.0, 40, n=40))
    assert v["undersized"] is True
    assert v["n_trades"] == 40


def test_tier0_handles_empty():
    v = tier0_verdict([])
    assert v["verdict"] == "KILL"
    assert v["n_trades"] == 0


def test_bootstrap_ci_brackets_the_mean():
    b = bootstrap_mean_ci(_series(1.0, 5), n_boot=2000)
    assert b["ci_low"] < b["mean"] < b["ci_high"]
    assert b["n"] == 300


def test_per_period_sharpe_zero_variance_is_zero():
    assert per_period_sharpe([0.01, 0.01, 0.01]) == 0.0


def test_per_period_sharpe_positive_for_positive_drift():
    rets = np.random.default_rng(3).normal(0.001, 0.01, 250)
    assert per_period_sharpe(rets) > 0
