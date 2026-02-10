"""
Service Factory — builds all ``MarketAgentService`` dependencies.

This module centralises dependency construction so that:

1. ``MarketAgentService.__init__`` becomes shorter and easier to read.
2. Tests can inject mock dependencies via ``ServiceDependencies`` without
   monkeypatching internal construction logic.
3. The dependency graph is documented in one place.

Usage (production — ``main.py``)::

    deps = build_service_dependencies(
        data_provider=data_provider,
        config=config,
        state_dir=state_dir,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
    )
    service = MarketAgentService(deps=deps)

Usage (tests)::

    deps = ServiceDependencies(
        data_provider=mock_provider,
        config=ConfigView({...}),
        state_dir=tmp_path,
        ...
    )
    service = MarketAgentService(deps=deps)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.config.config_view import ConfigView
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.market_agent.data_fetcher import MarketAgentDataFetcher
from pearlalgo.market_agent.health_monitor import HealthMonitor
from pearlalgo.market_agent.notification_queue import NotificationQueue
from pearlalgo.market_agent.performance_tracker import PerformanceTracker
from pearlalgo.market_agent.state_manager import MarketAgentStateManager
from pearlalgo.market_agent.telegram_notifier import MarketAgentTelegramNotifier
from pearlalgo.utils.logger import logger


@dataclass
class ServiceDependencies:
    """Container for all ``MarketAgentService`` dependencies.

    Every field has a sensible default (``None`` disables the component)
    so tests can provide only the subset they care about.  The factory
    function :func:`build_service_dependencies` populates all of them
    for production use.
    """

    # ---- required (no sensible default) ----
    data_provider: DataProvider = field(default=None)  # type: ignore[assignment]
    config: ConfigView = field(default=None)  # type: ignore[assignment]

    # ---- core infrastructure ----
    service_config: Dict[str, Any] = field(default_factory=dict)
    state_dir: Optional[Path] = None

    # ---- data / state / perf ----
    data_fetcher: Optional[MarketAgentDataFetcher] = None
    state_manager: Optional[MarketAgentStateManager] = None
    performance_tracker: Optional[PerformanceTracker] = None

    # ---- telegram ----
    telegram_notifier: Optional[MarketAgentTelegramNotifier] = None
    notification_queue: Optional[NotificationQueue] = None

    # ---- monitoring ----
    health_monitor: Optional[HealthMonitor] = None

    # ---- credentials (passed through for lazy construction) ----
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    def resolve_defaults(self) -> "ServiceDependencies":
        """Fill in ``None`` fields with sensible production defaults.

        This eliminates the dual construction path in
        ``MarketAgentService.__init__`` — the service now always receives
        a fully-populated ``ServiceDependencies``.

        Returns ``self`` for convenience (mutates in place).
        """
        if not self.service_config:
            self.service_config = load_service_config()

        if self.config is None:
            from pearlalgo.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
            self.config = ConfigView(PEARL_BOT_CONFIG.copy())

        symbol = str(self.config.get("symbol", "MNQ"))
        timeframe = str(self.config.get("timeframe", "5m"))

        if self.data_fetcher is None and self.data_provider is not None:
            nq_config_dict = {"symbol": symbol, "timeframe": timeframe}
            self.data_fetcher = MarketAgentDataFetcher(self.data_provider, config=nq_config_dict)

        if self.state_manager is None:
            self.state_manager = MarketAgentStateManager(
                state_dir=self.state_dir,
                service_config=self.service_config,
            )

        if self.performance_tracker is None:
            self.performance_tracker = PerformanceTracker(
                state_dir=self.state_dir,
                state_manager=self.state_manager,
            )

        if self.telegram_notifier is None:
            challenge_cfg = self.service_config.get("challenge", {}) or {}
            mffu_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
            account_label = (
                "MFFU"
                if mffu_stage in ("mffu_eval", "evaluation", "sim_funded", "live")
                else "INCEPTION"
            )
            self.telegram_notifier = MarketAgentTelegramNotifier(
                bot_token=self.telegram_bot_token,
                chat_id=self.telegram_chat_id,
                state_dir=self.state_dir,
                account_label=account_label,
            )

        if self.notification_queue is None:
            telegram_settings = self.service_config.get("telegram", {}) or {}
            min_tier = str(telegram_settings.get("notification_tier", "important") or "important")
            self.notification_queue = NotificationQueue(
                telegram_notifier=self.telegram_notifier,
                max_queue_size=1000,
                batch_delay_seconds=0.5,
                max_retries=3,
                min_tier=min_tier,
            )

        if self.health_monitor is None:
            self.health_monitor = HealthMonitor(state_dir=self.state_dir)

        return self


def build_service_dependencies(
    data_provider: DataProvider,
    config: ConfigView,
    *,
    state_dir: Optional[Path] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    service_config: Optional[Dict[str, Any]] = None,
) -> ServiceDependencies:
    """Construct a fully-populated :class:`ServiceDependencies`.

    This is the production construction path.  The service is free to
    override or extend any dependency it receives — the factory just
    provides the *initial* wiring.
    """

    if service_config is None:
        service_config = load_service_config()

    symbol = str(config.get("symbol", "MNQ"))
    timeframe = str(config.get("timeframe", "5m"))

    nq_config_dict = {"symbol": symbol, "timeframe": timeframe}
    data_fetcher = MarketAgentDataFetcher(data_provider, config=nq_config_dict)

    state_manager = MarketAgentStateManager(
        state_dir=state_dir,
        service_config=service_config,
    )

    performance_tracker = PerformanceTracker(
        state_dir=state_dir,
        state_manager=state_manager,
    )

    # Derive account label for Telegram messages
    challenge_cfg = service_config.get("challenge", {}) or {}
    mffu_stage = str(challenge_cfg.get("stage", "") or "").strip().lower()
    account_label = (
        "MFFU"
        if mffu_stage in ("mffu_eval", "evaluation", "sim_funded", "live")
        else "INCEPTION"
    )

    telegram_notifier = MarketAgentTelegramNotifier(
        bot_token=telegram_bot_token,
        chat_id=telegram_chat_id,
        state_dir=state_dir,
        account_label=account_label,
    )

    telegram_settings = service_config.get("telegram", {}) or {}
    min_tier = str(telegram_settings.get("notification_tier", "important") or "important")
    notification_queue = NotificationQueue(
        telegram_notifier=telegram_notifier,
        max_queue_size=1000,
        batch_delay_seconds=0.5,
        max_retries=3,
        min_tier=min_tier,
    )

    health_monitor = HealthMonitor(state_dir=state_dir)

    logger.debug("ServiceDependencies built via factory")

    return ServiceDependencies(
        data_provider=data_provider,
        config=config,
        service_config=service_config,
        state_dir=state_dir,
        data_fetcher=data_fetcher,
        state_manager=state_manager,
        performance_tracker=performance_tracker,
        telegram_notifier=telegram_notifier,
        notification_queue=notification_queue,
        health_monitor=health_monitor,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
