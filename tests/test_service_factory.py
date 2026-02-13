"""Tests for pearlalgo.market_agent.service_factory.

Covers ServiceDependencies dataclass, resolve_defaults(), build_service_dependencies(),
and the account_label derivation logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from pearlalgo.config.config_view import ConfigView
from pearlalgo.market_agent.service_factory import (
    ServiceDependencies,
    build_service_dependencies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_data_provider() -> MagicMock:
    """Lightweight mock DataProvider."""
    dp = MagicMock()
    dp.fetch_historical = MagicMock()
    return dp


def _minimal_config(**overrides: Any) -> ConfigView:
    """ConfigView with minimal keys needed by the factory."""
    base: Dict[str, Any] = {"symbol": "MNQ", "timeframe": "5m"}
    base.update(overrides)
    return ConfigView(base)


def _stub_service_config(**overrides: Any) -> Dict[str, Any]:
    """Service config dict with safe defaults."""
    cfg: Dict[str, Any] = {
        "challenge": {"stage": "ibkr_virtual"},
        "telegram": {"notification_tier": "important"},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# ServiceDependencies — default field values
# ---------------------------------------------------------------------------

class TestServiceDependenciesDefaults:
    """Optional sub-components default to None / empty so tests can inject only what they need."""

    def test_optional_fields_are_none_by_default(self) -> None:
        deps = ServiceDependencies()
        assert deps.data_fetcher is None
        assert deps.state_manager is None
        assert deps.performance_tracker is None
        assert deps.telegram_notifier is None
        assert deps.notification_queue is None
        assert deps.health_monitor is None
        assert deps.state_dir is None

    def test_service_config_defaults_to_empty_dict(self) -> None:
        deps = ServiceDependencies()
        assert deps.service_config == {}


# ---------------------------------------------------------------------------
# resolve_defaults()
# ---------------------------------------------------------------------------

class TestResolveDefaults:
    """resolve_defaults() should populate None fields using production constructors."""

    @patch("pearlalgo.market_agent.service_factory.load_service_config")
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_fills_none_fields(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        mock_load_cfg,
        tmp_path: Path,
    ) -> None:
        mock_load_cfg.return_value = _stub_service_config()
        mock_state_mgr_cls.return_value.state_dir = tmp_path

        deps = ServiceDependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
        )
        result = deps.resolve_defaults()

        # Returns self (mutates in place)
        assert result is deps

        # All previously-None fields should now be populated
        assert deps.data_fetcher is not None
        assert deps.state_manager is not None
        assert deps.performance_tracker is not None
        assert deps.telegram_notifier is not None
        assert deps.notification_queue is not None
        assert deps.health_monitor is not None

    @patch("pearlalgo.market_agent.service_factory.load_service_config")
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_does_not_overwrite_pre_set_fields(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        mock_load_cfg,
        tmp_path: Path,
    ) -> None:
        mock_load_cfg.return_value = _stub_service_config()
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        custom_fetcher = MagicMock(name="custom_fetcher")

        deps = ServiceDependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            data_fetcher=custom_fetcher,
        )
        deps.resolve_defaults()

        # Pre-set data_fetcher must survive resolve_defaults()
        assert deps.data_fetcher is custom_fetcher
        # MarketAgentDataFetcher constructor should NOT have been called
        mock_fetcher_cls.assert_not_called()

    @patch("pearlalgo.market_agent.service_factory.load_service_config")
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    def test_loads_service_config_when_empty(
        self,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        mock_load_cfg,
        tmp_path: Path,
    ) -> None:
        mock_load_cfg.return_value = _stub_service_config()
        mock_state_mgr_cls.return_value.state_dir = tmp_path

        deps = ServiceDependencies(
            config=_minimal_config(),
            service_config={},  # empty → should trigger load
        )
        deps.resolve_defaults()

        mock_load_cfg.assert_called_once()
        assert deps.service_config == _stub_service_config()


# ---------------------------------------------------------------------------
# build_service_dependencies()
# ---------------------------------------------------------------------------

class TestBuildServiceDependencies:
    """build_service_dependencies() should return a fully-populated ServiceDependencies."""

    @patch("pearlalgo.market_agent.service_factory.load_service_config")
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_build_service_dependencies_returns_fully_populated_instance(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        mock_load_cfg,
        tmp_path: Path,
    ) -> None:
        mock_load_cfg.return_value = _stub_service_config()
        mock_state_mgr_cls.return_value.state_dir = tmp_path

        deps = build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            telegram_bot_token="tok",
            telegram_chat_id="cid",
            service_config=_stub_service_config(),
        )

        assert isinstance(deps, ServiceDependencies)
        assert deps.data_fetcher is not None
        assert deps.state_manager is not None
        assert deps.performance_tracker is not None
        assert deps.telegram_notifier is not None
        assert deps.notification_queue is not None
        assert deps.health_monitor is not None

    @patch("pearlalgo.market_agent.service_factory.load_service_config")
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_loads_service_config_when_none(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        mock_load_cfg,
        tmp_path: Path,
    ) -> None:
        expected_cfg = _stub_service_config()
        mock_load_cfg.return_value = expected_cfg
        mock_state_mgr_cls.return_value.state_dir = tmp_path

        deps = build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            service_config=None,  # triggers load_service_config()
        )

        mock_load_cfg.assert_called_once()
        assert deps.service_config == expected_cfg


# ---------------------------------------------------------------------------
# account_label derivation (Tradovate Paper vs IBKR Virtual)
# ---------------------------------------------------------------------------

class TestAccountLabel:
    """The factory derives the Telegram account_label from challenge.stage."""

    @pytest.mark.parametrize(
        "stage",
        ["tv_paper_eval", "evaluation", "sim_funded", "live"],
    )
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_tv_paper_stages_produce_tv_paper_label(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        stage: str,
        tmp_path: Path,
    ) -> None:
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        svc_cfg = _stub_service_config(challenge={"stage": stage})

        build_service_dependencies(
            data_provider=_mock_data_provider(),
            config=_minimal_config(),
            state_dir=tmp_path,
            service_config=svc_cfg,
        )

        # The notifier should have been constructed with account_label="TV-PAPER"
        mock_tg_cls.assert_called_once()
        call_kwargs = mock_tg_cls.call_args
        assert call_kwargs.kwargs.get("account_label") == "TV-PAPER" or (
            call_kwargs.args and "TV-PAPER" in call_kwargs.args
        )

    @pytest.mark.parametrize(
        "stage",
        ["ibkr_virtual", "", "unknown", "paper"],
    )
    @patch("pearlalgo.market_agent.service_factory.HealthMonitor")
    @patch("pearlalgo.market_agent.service_factory.NotificationQueue")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentTelegramNotifier")
    @patch("pearlalgo.market_agent.service_factory.PerformanceTracker")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentStateManager")
    @patch("pearlalgo.market_agent.service_factory.MarketAgentDataFetcher")
    def test_non_tv_paper_stages_produce_tv_paper_label_too(
        self,
        mock_fetcher_cls,
        mock_state_mgr_cls,
        mock_perf_cls,
        mock_tg_cls,
        mock_nq_cls,
        mock_health_cls,
        stage: str,
        tmp_path: Path,
    ) -> None:
        """After Tradovate-only consolidation, all stages produce TV-PAPER."""
        mock_state_mgr_cls.return_value.state_dir = tmp_path
        svc_cfg = _stub_service_config(challenge={"stage": stage})

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


# ---------------------------------------------------------------------------
# Real-wiring test — only external I/O mocked
# ---------------------------------------------------------------------------


class TestRealWiringBuildDependencies:
    """build_service_dependencies() with real constructors — only external I/O mocked."""

    def test_service_factory_builds_real_dependencies_with_mock_io(
        self,
        tmp_path: Path,
        mock_data_provider,
    ) -> None:
        """Use the real factory with only IBKR connection and Telegram mocked.

        Verifies that every dependency is a genuine production instance and
        that the state manager can round-trip data through the filesystem.
        """
        from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher
        from pearlalgo.market_agent.health_monitor import HealthMonitor
        from pearlalgo.market_agent.notification_queue import NotificationQueue
        from pearlalgo.market_agent.performance_tracker import PerformanceTracker
        from pearlalgo.market_agent.state_manager import MarketAgentStateManager

        config = _minimal_config(symbol="MNQ", timeframe="5m")
        service_cfg = _stub_service_config()

        deps = build_service_dependencies(
            data_provider=mock_data_provider,
            config=config,
            state_dir=tmp_path,
            telegram_bot_token=None,   # disabled — no network
            telegram_chat_id=None,
            service_config=service_cfg,
        )

        assert isinstance(deps, ServiceDependencies)

        # StateManager is a real instance that can save/load from disk
        assert isinstance(deps.state_manager, MarketAgentStateManager)
        deps.state_manager.save_state({"integration_test": True, "counter": 1})
        loaded = deps.state_manager.load_state()
        assert loaded["integration_test"] is True
        assert loaded["counter"] == 1

        # PerformanceTracker is a real instance
        assert isinstance(deps.performance_tracker, PerformanceTracker)

        # DataFetcher wraps the real mock data provider (not a MagicMock)
        assert isinstance(deps.data_fetcher, MarketAgentDataFetcher)
        assert deps.data_fetcher.data_provider is mock_data_provider

        # HealthMonitor and NotificationQueue are non-None real instances
        assert isinstance(deps.health_monitor, HealthMonitor)
        assert isinstance(deps.notification_queue, NotificationQueue)
