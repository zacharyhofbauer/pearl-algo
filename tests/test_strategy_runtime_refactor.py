from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from pearlalgo.config.config_view import ConfigView
from pearlalgo.strategies.registry import create_strategy
from pearlalgo.strategies.composite_intraday import check_trading_session
from tests.mock_data_provider import MockDataProvider


def test_create_strategy_returns_composite_intraday():
    strategy = create_strategy(ConfigView({"strategy": {"active": "composite_intraday"}}))
    assert strategy.name == "composite_intraday"


def test_session_window_can_be_disabled():
    config = ConfigView(
        {
            "strategy": {"active": "composite_intraday", "enforce_session_window": False},
            "session": {"start_time": "09:30", "end_time": "16:00"},
        }
    )
    dt = datetime(2026, 4, 1, 2, 0, tzinfo=timezone.utc)
    assert check_trading_session(dt, config) is True


def test_composite_intraday_strategy_delegates_to_legacy_core():
    config = ConfigView({"strategy": {"active": "composite_intraday"}})
    strategy = create_strategy(config)
    df = pd.DataFrame(
        {
            "open": [1, 2],
            "high": [1, 2],
            "low": [1, 2],
            "close": [1, 2],
            "volume": [10, 11],
        }
    )

    with patch("pearlalgo.trading_bots.signal_generator.generate_signals", return_value=[{"type": "pearlbot_pinescript"}]) as mock_generate:
        result = strategy.analyze(df, current_time=datetime.now(timezone.utc))

    assert result == [{"type": "pearlbot_pinescript"}]
    mock_generate.assert_called_once()


def test_canonical_runtime_disables_legacy_signal_gate(tmp_path):
    service_config = {
        "service": {"status_update_interval": 900, "heartbeat_interval": 3600, "state_save_interval": 10},
        "circuit_breaker": {"max_consecutive_errors": 10, "max_data_fetch_errors": 5, "max_connection_failures": 10},
        "trading_circuit_breaker": {"enabled": True},
        "guardrails": {"signal_gate_enabled": False},
        "strategy": {"active": "composite_intraday", "enforce_session_window": False},
        "signals": {},
        "risk": {},
        "telegram": {},
        "telegram_ui": {},
        "auto_flat": {},
        "data": {"stale_data_threshold_minutes": 10, "buffer_size": 100},
        "storage": {"sqlite_enabled": False},
        "challenge": {},
        "execution": {"enabled": False},
    }

    provider = MockDataProvider(
        simulate_delayed_data=False,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )

    with patch("pearlalgo.market_agent.service.load_service_config", return_value=service_config.copy()):
        from pearlalgo.market_agent.service import MarketAgentService

        service = MarketAgentService(
            data_provider=provider,
            state_dir=tmp_path,
            config={
                "symbol": "MNQ",
                "timeframe": "1m",
                "scan_interval": 30,
                "strategy": {"active": "composite_intraday", "enforce_session_window": False},
            },
        )

    assert service.strategy.name == "composite_intraday"
    # FIXED 2026-04-08: CB is now always created from guardrails config,
    # regardless of signal_gate_enabled.  The old behavior (CB=None when
    # signal_gate_enabled=false + active strategy) was a bug that left the
    # system unprotected.
    assert service.trading_circuit_breaker is not None
