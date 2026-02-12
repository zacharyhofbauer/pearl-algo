"""Tests for Telegram account label derivation logic.

Uses mocks to avoid heavy dependencies from resolve_defaults().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.market_agent.service_factory import (
    ServiceDependencies,
    build_service_dependencies,
)


def _mock_data_provider() -> MagicMock:
    dp = MagicMock()
    dp.fetch_historical = MagicMock()
    return dp


def _minimal_config() -> MagicMock:
    from pearlalgo.config.config_view import ConfigView
    return ConfigView({"symbol": "MNQ", "timeframe": "5m"})


def _stub_service_config(**overrides: Any) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "challenge": {"stage": "ibkr_virtual"},
        "telegram": {"notification_tier": "important"},
    }
    cfg.update(overrides)
    return cfg


class TestTelegramAccountLabels:
    """Test that the factory derives correct Telegram account labels."""

    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_ibkr_virtual_account_gets_ibkr_vir_label(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        tmp_path: Path,
    ) -> None:
        """IBKR Virtual account should produce the IBKR-VIR label."""
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        svc_cfg = _stub_service_config(challenge={"stage": "ibkr_virtual"})

        build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            service_config=svc_cfg,
        )

        mock_tg_cls.assert_called_once()
        call_kwargs = mock_tg_cls.call_args
        assert call_kwargs.kwargs.get("account_label") == "IBKR-VIR" or (
            call_kwargs.args and "IBKR-VIR" in call_kwargs.args
        )

    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_tv_paper_account_gets_tv_paper_label(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        tmp_path: Path,
    ) -> None:
        """Tradovate Paper account should produce the TV-PAPER label."""
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        svc_cfg = _stub_service_config(challenge={"stage": "tv_paper_eval"})

        build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            service_config=svc_cfg,
        )

        mock_tg_cls.assert_called_once()
        call_kwargs = mock_tg_cls.call_args
        assert call_kwargs.kwargs.get("account_label") == "TV-PAPER" or (
            call_kwargs.args and "TV-PAPER" in call_kwargs.args
        )

    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_no_accounts_config_falls_back_to_ibkr_vir(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        tmp_path: Path,
    ) -> None:
        """Without accounts config, the label should fall back to IBKR-VIR."""
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        svc_cfg = _stub_service_config(challenge={"stage": ""})

        build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            service_config=svc_cfg,
        )

        mock_tg_cls.assert_called_once()
        call_kwargs = mock_tg_cls.call_args
        assert call_kwargs.kwargs.get("account_label") == "IBKR-VIR" or (
            call_kwargs.args and "IBKR-VIR" in call_kwargs.args
        )
