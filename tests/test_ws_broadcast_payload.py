"""
Runtime tests for the shared WebSocket broadcast payload contract.

These tests intentionally validate behavior through the shared payload builder
instead of matching source strings in ``server.py``.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

from pearlalgo.api import server as server_mod


REQUIRED_WS_KEYS = {
    "running",
    "paused",
    "daily_pnl",
    "daily_trades",
    "daily_wins",
    "daily_losses",
    "active_trades_count",
    "active_trades_unrealized_pnl",
    "futures_market_open",
    "data_fresh",
    "last_updated",
    "ai_status",
    "challenge",
    "recent_exits",
    "performance",
    "equity_curve",
    "risk_metrics",
    "positions",
    "recent_trades",
    "performance_summary",
    "cadence_metrics",
    "market_regime",
    "buy_sell_pressure",
    "signal_rejections_24h",
    "last_signal_decision",
    "shadow_counters",
    "execution_state",
    "tradovate_account",
    "circuit_breaker",
    "ml_filter_performance",
    "session_context",
    "signal_activity",
    "gateway_status",
    "connection_health",
    "error_summary",
    "config",
    "data_quality",
    "pearl_suggestion",
    "pearl_insights",
    "pearl_ai_available",
    "pearl_feed",
    "pearl_ai_heartbeat",
    "pearl_ai_debug",
    "operator_lock_enabled",
}


class TestBroadcastPayloadContract:
    def test_builder_returns_required_runtime_keys(self, tmp_path: Path):
        state = {
            "running": True,
            "paused": False,
            "futures_market_open": True,
            "data_fresh": True,
            "active_trades_count": 1,
            "active_trades_unrealized_pnl": 7.5,
            "buy_sell_pressure_raw": {"buy": 0.55, "sell": 0.45},
            "execution_state": {"mode": "shadow"},
            "tradovate_account": {"equity": 50020.0},
            "circuit_breaker": {"armed": False},
            "ml_filter_performance": {"lift": 1.1},
            "session_context": {"session": "ny"},
            "signal_activity": {"generated": 2},
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(server_mod, "_cached", side_effect=lambda _key, _ttl, fn, *args, **kwargs: fn(*args, **kwargs))
            )
            stack.enter_context(patch.object(server_mod, "_compute_daily_stats", return_value={
                "daily_pnl": 10.0,
                "daily_trades": 2,
                "daily_wins": 1,
                "daily_losses": 1,
                "pnl_source": "tradovate_fills",
                "tradovate_positions": 1,
                "tradovate_open_pnl": 3.5,
            }))
            stack.enter_context(patch.object(server_mod, "_get_ai_status", return_value={"bandit_mode": "off"}))
            stack.enter_context(patch.object(server_mod, "_get_challenge_status", return_value={"enabled": True}))
            stack.enter_context(patch.object(server_mod, "_get_recent_exits", return_value=[]))
            stack.enter_context(
                patch.object(server_mod, "_compute_performance_stats", return_value={"24h": {"pnl": 10.0}})
            )
            stack.enter_context(patch.object(server_mod, "_get_equity_curve", return_value=[]))
            stack.enter_context(patch.object(server_mod, "_get_risk_metrics", return_value={"max_drawdown": -10.0}))
            stack.enter_context(patch.object(server_mod, "_get_positions_for_broadcast", return_value=[]))
            stack.enter_context(patch.object(server_mod, "_get_trades_for_broadcast", return_value=[]))
            stack.enter_context(
                patch.object(server_mod, "_get_performance_summary_for_broadcast", return_value={"all": {"pnl": 10.0}})
            )
            stack.enter_context(patch.object(server_mod, "_get_cadence_metrics_enhanced", return_value={"cycles": 5}))
            stack.enter_context(
                patch.object(server_mod, "_get_market_regime", return_value={"regime": "ranging", "confidence": 0.7})
            )
            stack.enter_context(
                patch.object(server_mod, "_get_signal_rejections_24h", return_value={"direction_gating": 1})
            )
            stack.enter_context(
                patch.object(server_mod, "_get_last_signal_decision", return_value={"allowed": True})
            )
            stack.enter_context(
                patch.object(server_mod, "_get_shadow_counters", return_value={"generated": 1})
            )
            stack.enter_context(patch.object(server_mod, "_get_gateway_status", return_value={"connected": True}))
            stack.enter_context(
                patch.object(server_mod, "_get_connection_health", return_value={"status": "healthy"})
            )
            stack.enter_context(patch.object(server_mod, "_get_error_summary", return_value={"recent_errors": 0}))
            stack.enter_context(patch.object(server_mod, "_get_config", return_value={"symbol": "MNQ"}))
            stack.enter_context(patch.object(server_mod, "_get_data_quality", return_value={"freshness": "good"}))
            stack.enter_context(patch.object(server_mod, "_operator_enabled", False))
            payload = server_mod._build_ws_state_payload(tmp_path, state)

        missing = REQUIRED_WS_KEYS - set(payload.keys())
        assert not missing, f"Missing runtime payload keys: {sorted(missing)}"


class TestMetricsModuleContract:
    def test_compute_risk_metrics_importable(self):
        from pearlalgo.api.metrics import DEFAULT_RISK_METRICS, compute_risk_metrics

        assert callable(compute_risk_metrics)
        assert isinstance(DEFAULT_RISK_METRICS, dict)

    def test_default_metrics_has_new_keys(self):
        from pearlalgo.api.metrics import DEFAULT_RISK_METRICS

        new_keys = {
            "sortino_ratio",
            "calmar_ratio",
            "kelly_criterion",
            "max_consecutive_wins",
            "max_consecutive_losses",
            "current_streak",
            "max_drawdown_duration_seconds",
        }
        missing = new_keys - set(DEFAULT_RISK_METRICS.keys())
        assert not missing, f"Missing keys in DEFAULT_RISK_METRICS: {missing}"


class TestDataLayerContract:
    def test_is_tv_paper_account_importable(self):
        from pearlalgo.api.data_layer import is_tv_paper_account

        assert callable(is_tv_paper_account)

    def test_get_signals_importable(self):
        from pearlalgo.api.data_layer import get_signals

        assert callable(get_signals)

    def test_cached_importable(self):
        from pearlalgo.api.data_layer import cached

        assert callable(cached)


class TestTradovateHelpersContract:
    def test_get_paired_tradovate_trades_importable(self):
        from pearlalgo.api.tradovate_helpers import get_paired_tradovate_trades

        assert callable(get_paired_tradovate_trades)

    def test_tradovate_positions_for_api_importable(self):
        from pearlalgo.api.tradovate_helpers import tradovate_positions_for_api

        assert callable(tradovate_positions_for_api)


class TestBroadcastHelpersExist:
    def test_broadcast_helpers_are_importable(self):
        assert callable(server_mod._build_ws_state_payload)
        assert callable(server_mod._get_positions_for_broadcast)
        assert callable(server_mod._get_trades_for_broadcast)
        assert callable(server_mod._get_performance_summary_for_broadcast)
