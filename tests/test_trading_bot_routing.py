from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from pearlalgo.strategies.nq_intraday.signal_generator import NQSignalGenerator


class DummyScanner:
    def is_market_hours(self, dt=None) -> bool:
        return True

    def scan(self, df, df_5m=None, df_15m=None, market_data=None):
        return [
            {
                "type": "scanner_signal",
                "direction": "long",
                "confidence": 1.0,
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "risk_reward": 2.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

    def get_gate_reasons(self):
        return []


class DummyTradingBotManager:
    def analyze(self, market_data):
        return [
            {
                "type": "trading_bot_PearlAutoBot",
                "direction": "long",
                "confidence": 1.0,
                "entry_price": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "risk_reward": 2.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]


def test_trading_bot_replaces_scanner_signals(monkeypatch):
    service_config = {
        "signals": {
            "duplicate_window_seconds": 300,
            "min_confidence": 0.0,
            "min_risk_reward": 0.0,
            "duplicate_price_threshold_pct": 0.0,
        },
        "risk": {"take_profit_risk_reward": 1.0},
        "trading_bot": {
            "enabled": True,
            "selected": "PearlAutoBot",
            "available": {"PearlAutoBot": {"class": "PearlAutoBot", "enabled": True}},
        },
    }

    monkeypatch.setattr(
        "pearlalgo.strategies.nq_intraday.signal_generator.load_service_config",
        lambda: service_config,
    )
    monkeypatch.setattr(
        "pearlalgo.strategies.nq_intraday.signal_generator.get_trading_bot_manager",
        lambda: DummyTradingBotManager(),
    )

    generator = NQSignalGenerator(config=NQIntradayConfig(), scanner=DummyScanner())
    generator._policy = None
    generator._check_regime_filter = lambda signal: {"passed": True}
    generator._validate_signal_with_reason = lambda signal, min_confidence, min_risk_reward: {"valid": True}

    df = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [100, 120],
        },
        index=pd.date_range("2025-01-01", periods=2, freq="1min", tz="UTC"),
    )
    market_data = {"df": df, "latest_bar": {"timestamp": df.index[-1]}}

    signals = generator.generate(market_data)

    assert signals
    assert all(s.get("type", "").startswith("trading_bot_") for s in signals)
    assert not any(s.get("type") == "scanner_signal" for s in signals)
