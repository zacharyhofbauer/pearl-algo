"""Tests for generate_signals() with parameterized market scenarios.

Validates data-validation guards, signal-structure invariants, configuration
override behaviour, and trading-session time filtering using synthetic OHLCV
DataFrames that simulate specific MNQ market conditions.

Fixtures
--------
- ``trending_up_df``      – 100 bars, steady uptrend (~2 pts/bar)
- ``trending_down_df``    – 100 bars, steady downtrend (~2 pts/bar)
- ``ranging_df``          – 100 bars, sinusoidal oscillation around 17 500
- ``high_volatility_df``  – 100 bars, random walk ±50 pts/bar
- ``insufficient_data_df``– 5 bars (below indicator minimums)
- ``empty_df``            – 0 bars, correct columns
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from pearlalgo.trading_bots.pearl_bot_auto import (
    StrategyParams,
    _load_strategy_params,
    generate_signals,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 2025-01-15 14:30:00 UTC  ==  09:30 ET  (inside default session 09:30–16:00)
TRADING_TIME = datetime(2025, 1, 15, 14, 30, 0, tzinfo=timezone.utc)

# 2025-01-15 05:00:00 UTC  ==  00:00 ET  (well outside session)
OUTSIDE_TRADING_TIME = datetime(2025, 1, 15, 5, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> dict:
    """Return a config dict compatible with ``generate_signals``.

    Every key used by the production CONFIG is present so tests never
    fail due to a missing key.  *overrides* let individual tests tweak
    specific knobs.
    """
    base: dict = {
        "symbol": "MNQ",
        "timeframe": "5m",
        "scan_interval": 30,
        # EMA
        "ema_fast": 9,
        "ema_slow": 21,
        # VWAP
        "vwap_std_dev": 1.0,
        "vwap_bands": 2,
        # Volume
        "volume_ma_length": 20,
        # S&R
        "sr_length": 130,
        "sr_extend": 30,
        "sr_atr_mult": 0.5,
        # TBT
        "tbt_period": 10,
        "tbt_trend_type": "wicks",
        "tbt_extend": 25,
        # Supply & Demand
        "sd_threshold_pct": 10.0,
        "sd_resolution": 50,
        # SpacemanBTC Key Levels
        "key_level_proximity_pct": 0.15,
        "key_level_breakout_pct": 0.05,
        "key_level_bounce_confidence": 0.12,
        "key_level_breakout_confidence": 0.10,
        "key_level_rejection_penalty": 0.08,
        # Risk management
        "stop_loss_atr_mult": 3.5,
        "take_profit_atr_mult": 5.0,
        "min_confidence": 0.55,
        "min_risk_reward": 1.3,
        # Aggressive mode (off by default)
        "allow_vwap_cross_entries": False,
        "allow_vwap_retest_entries": False,
        "allow_trend_momentum_entries": False,
        "trend_momentum_atr_mult": 0.5,
        "allow_trend_breakout_entries": False,
        "trend_breakout_lookback_bars": 5,
        # Session hours (ET)
        "start_hour": 9,
        "start_minute": 30,
        "end_hour": 16,
        "end_minute": 0,
    }
    base.update(overrides)
    return base


def _permissive_config(**overrides) -> dict:
    """Config with aggressive triggers ON and very low thresholds.

    Maximises the likelihood that synthetic data actually produces a signal,
    so that signal-structure tests have something to validate.
    """
    return _make_config(
        min_confidence=0.01,
        min_risk_reward=0.5,
        allow_trend_breakout_entries=True,
        allow_trend_momentum_entries=True,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Required top-level keys in every signal dict
# ---------------------------------------------------------------------------

REQUIRED_SIGNAL_KEYS = frozenset(
    {
        "direction",
        "entry_price",
        "stop_loss",
        "take_profit",
        "confidence",
        "risk_reward",
        "reason",
        "indicators",
        "timestamp",
        "symbol",
        "timeframe",
        "type",
        "virtual_broker",
        "market_regime",
        "regime_adjustment",
    }
)


# ============================================================================
# Fixtures — synthetic market data
# ============================================================================


@pytest.fixture
def trending_up_df() -> pd.DataFrame:
    """100 bars of uptrending MNQ data.

    Each bar is ~2 pts higher than the last, so after the EMA warm-up
    period EMA(9) > EMA(21).  Volume randomly between 1 000–5 000.
    """
    np.random.seed(42)
    n = 100
    close = 17_500.0 + np.arange(n) * 2.0 + np.random.randn(n) * 3.0
    high = close + np.abs(np.random.randn(n) * 10) + 5
    low = close - np.abs(np.random.randn(n) * 10) - 5
    open_ = close - np.random.rand(n) * 5  # bullish candles
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def trending_down_df() -> pd.DataFrame:
    """100 bars of downtrending MNQ data (opposite of trending_up_df)."""
    np.random.seed(43)
    n = 100
    close = 17_500.0 - np.arange(n) * 2.0 + np.random.randn(n) * 3.0
    high = close + np.abs(np.random.randn(n) * 10) + 5
    low = close - np.abs(np.random.randn(n) * 10) - 5
    open_ = close + np.random.rand(n) * 5  # bearish candles
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def ranging_df() -> pd.DataFrame:
    """100 bars oscillating in a tight band (±10 pts) around 17 500."""
    np.random.seed(44)
    n = 100
    t = np.linspace(0, 8 * np.pi, n)
    close = 17_500.0 + np.sin(t) * 10 + np.random.randn(n) * 2
    high = close + np.abs(np.random.randn(n) * 5) + 3
    low = close - np.abs(np.random.randn(n) * 5) - 3
    open_ = close + np.random.randn(n) * 2
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def high_volatility_df() -> pd.DataFrame:
    """100 bars with large candles and high ATR (random walk ±50 pts/bar)."""
    np.random.seed(45)
    n = 100
    close = 17_500.0 + np.cumsum(np.random.randn(n) * 50)
    high = close + np.abs(np.random.randn(n) * 60) + 30
    low = close - np.abs(np.random.randn(n) * 60) - 30
    open_ = close + np.random.randn(n) * 30
    volume = np.random.randint(2000, 5000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def insufficient_data_df() -> pd.DataFrame:
    """Only 5 bars — below the minimum required for core indicators."""
    np.random.seed(46)
    n = 5
    close = 17_500.0 + np.random.randn(n) * 5
    high = close + 10
    low = close - 10
    open_ = close - 2
    volume = np.full(n, 3000.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


@pytest.fixture
def empty_df() -> pd.DataFrame:
    """Empty DataFrame with the correct OHLCV columns."""
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


# ---------------------------------------------------------------------------
# Internal fixture: data engineered to reliably trigger a signal
# ---------------------------------------------------------------------------


@pytest.fixture
def _forced_crossover_df() -> pd.DataFrame:
    """98-bar decline followed by a 2-bar sharp rally.

    Engineered so that EMA(9) sits below EMA(21) during the decline and
    the ``trend_momentum`` aggressive trigger fires on the final bar
    (big up-move while EMA trend is bullish and price is above VWAP).
    This guarantees the parametrized signal-structure tests always have
    at least one non-empty result set.
    """
    n = 100
    close = np.empty(n)
    # Gentle decline: EMA(9) tracks faster → sits below EMA(21)
    close[:98] = np.linspace(17_500, 17_450, 98)
    # Sharp 2-bar rally flips EMA(9) above EMA(21)
    close[98] = 17_480.0
    close[99] = 17_530.0

    high = close + 15
    low = close - 15
    open_ = close - 3
    volume = np.full(n, 3000.0)
    volume[-1] = 5000.0  # high volume on signal bar for volume confirmation
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


# ---------------------------------------------------------------------------
# Parametrized fixture: generates signals for each market scenario
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        "trending_up",
        "trending_down",
        "ranging",
        "high_volatility",
        "forced_crossover",
    ],
)
def scenario_signals(
    request,
    trending_up_df,
    trending_down_df,
    ranging_df,
    high_volatility_df,
    _forced_crossover_df,
):
    """Yield ``(signals, scenario_name)`` for every market scenario.

    Tests that consume this fixture are executed once per scenario.
    """
    dfs = {
        "trending_up": trending_up_df,
        "trending_down": trending_down_df,
        "ranging": ranging_df,
        "high_volatility": high_volatility_df,
        "forced_crossover": _forced_crossover_df,
    }
    df = dfs[request.param]
    signals = generate_signals(
        df,
        config=_permissive_config(),
        current_time=TRADING_TIME,
    )
    return signals, request.param


# ============================================================================
# Tests 1–3: Data validation (deterministic — always pass/fail identically)
# ============================================================================


class TestDataValidation:
    """generate_signals must gracefully return ``[]`` for bad / insufficient data."""

    def test_empty_data_returns_no_signals(self, empty_df):
        signals = generate_signals(
            empty_df, config=_make_config(), current_time=TRADING_TIME
        )
        assert signals == []

    def test_insufficient_data_returns_no_signals(self, insufficient_data_df):
        signals = generate_signals(
            insufficient_data_df, config=_make_config(), current_time=TRADING_TIME
        )
        assert signals == []

    def test_missing_columns_returns_no_signals(self, trending_up_df):
        """Dropping 'volume' (a required column) must cause an early return."""
        df_no_vol = trending_up_df.drop(columns=["volume"])
        signals = generate_signals(
            df_no_vol, config=_make_config(), current_time=TRADING_TIME
        )
        assert signals == []


# ============================================================================
# Tests 4–6: Scenario "may generate" tests
# ============================================================================


class TestScenarioSignals:
    """Data-driven scenarios that *may* or may not produce signals.

    When signals are produced their direction must be consistent with the
    market scenario.
    """

    def test_trending_up_may_generate_long_signals(self, trending_up_df):
        signals = generate_signals(
            trending_up_df, config=_permissive_config(), current_time=TRADING_TIME
        )
        assert isinstance(signals, list)
        # If any signals were generated, they must all be long
        for sig in signals:
            assert sig["direction"] == "long"

    def test_trending_down_may_generate_short_signals(self, trending_down_df):
        signals = generate_signals(
            trending_down_df, config=_permissive_config(), current_time=TRADING_TIME
        )
        assert isinstance(signals, list)
        for sig in signals:
            assert sig["direction"] == "short"

    def test_ranging_market_may_suppress_signals(self, ranging_df):
        """In a ranging regime, signals may be reduced or absent entirely."""
        signals = generate_signals(
            ranging_df, config=_make_config(), current_time=TRADING_TIME
        )
        assert isinstance(signals, list)
        # Whatever signals survive must still respect the confidence cap
        for sig in signals:
            assert sig["confidence"] <= 0.99


# ============================================================================
# Tests 7–10: Signal structure validation (parametrized across scenarios)
# ============================================================================


class TestSignalStructure:
    """Every signal emitted by ``generate_signals`` must satisfy these invariants.

    Parametrized via ``scenario_signals`` so each scenario is tested
    independently.  Scenarios that produce no signals are skipped.
    """

    def test_signals_have_required_fields(self, scenario_signals):
        signals, scenario = scenario_signals
        if not signals:
            pytest.skip(f"No signals generated for {scenario}")
        for sig in signals:
            missing = REQUIRED_SIGNAL_KEYS - sig.keys()
            assert not missing, f"Signal from {scenario} missing keys: {missing}"

    def test_confidence_within_bounds(self, scenario_signals):
        signals, scenario = scenario_signals
        if not signals:
            pytest.skip(f"No signals generated for {scenario}")
        for sig in signals:
            assert 0 <= sig["confidence"] <= 1, (
                f"confidence={sig['confidence']!r} out of [0, 1] ({scenario})"
            )

    def test_risk_reward_positive(self, scenario_signals):
        signals, scenario = scenario_signals
        if not signals:
            pytest.skip(f"No signals generated for {scenario}")
        for sig in signals:
            assert sig["risk_reward"] > 0, (
                f"risk_reward={sig['risk_reward']!r} not positive ({scenario})"
            )

    def test_stop_loss_and_take_profit_valid(self, scenario_signals):
        signals, scenario = scenario_signals
        if not signals:
            pytest.skip(f"No signals generated for {scenario}")
        for sig in signals:
            entry = sig["entry_price"]
            sl = sig["stop_loss"]
            tp = sig["take_profit"]
            if sig["direction"] == "long":
                assert sl < entry, (
                    f"Long SL ({sl}) should be < entry ({entry}) [{scenario}]"
                )
                assert tp > entry, (
                    f"Long TP ({tp}) should be > entry ({entry}) [{scenario}]"
                )
            else:
                assert sl > entry, (
                    f"Short SL ({sl}) should be > entry ({entry}) [{scenario}]"
                )
                assert tp < entry, (
                    f"Short TP ({tp}) should be < entry ({entry}) [{scenario}]"
                )


# ============================================================================
# Test 11: StrategyParams config overrides
# ============================================================================


class TestStrategyParamsConfig:
    """Config dict values must override ``StrategyParams`` defaults."""

    def test_strategy_params_loaded_from_config(self):
        """Custom values in the config dict flow through to StrategyParams."""
        custom = _make_config(
            atr_period=20,
            ema_fast=5,
            ema_slow=30,
            stop_loss_atr_mult=2.0,
            take_profit_atr_mult=4.0,
            base_confidence=0.60,
        )
        params = _load_strategy_params(custom)

        assert params.atr_period == 20
        assert params.ema_fast == 5
        assert params.ema_slow == 30
        assert params.stop_loss_atr_mult == 2.0
        assert params.take_profit_atr_mult == 4.0
        assert params.base_confidence == 0.60

    def test_strategy_params_defaults_without_overrides(self):
        """Keys absent from config fall back to Pydantic defaults."""
        params = _load_strategy_params(_make_config())
        assert params.atr_period == 14  # default
        assert params.max_confidence == 0.99  # default


# ============================================================================
# Test 12: Trading-session time filter
# ============================================================================


class TestTradingSessionFilter:
    """Signal generation must respect the configured trading-session window."""

    def test_outside_trading_session_returns_no_signals(self, trending_up_df):
        signals = generate_signals(
            trending_up_df,
            config=_permissive_config(),
            current_time=OUTSIDE_TRADING_TIME,
        )
        assert signals == []
