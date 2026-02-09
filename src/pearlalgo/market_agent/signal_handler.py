"""
Signal Handler Module

Handles signal processing, ML filtering, policy decisions, and execution.
Extracted from service.py for better code organization.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TYPE_CHECKING

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager
    from pearlalgo.market_agent.performance_tracker import PerformanceTracker
    from pearlalgo.market_agent.trading_circuit_breaker import TradingCircuitBreaker
    from pearlalgo.market_agent.notification_queue import NotificationQueue
    from pearlalgo.market_agent.order_manager import OrderManager
    from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig
    from pearlalgo.learning.contextual_bandit import ContextualBanditPolicy, ContextFeatures
    from pearlalgo.learning.ml_signal_filter import MLSignalFilter


class SignalHandler:
    """
    Handles signal processing pipeline.

    Responsibilities:
    - Circuit breaker checks
    - ML filter predictions (shadow mode)
    - Policy decisions (bandit/contextual)
    - Execution coordination
    - Notification queuing
    """

    def __init__(
        self,
        state_manager: "MarketAgentStateManager",
        performance_tracker: "PerformanceTracker",
        notification_queue: "NotificationQueue",
        order_manager: "OrderManager",
        *,
        trading_circuit_breaker: Optional["TradingCircuitBreaker"] = None,
        bandit_policy: Optional["BanditPolicy"] = None,
        bandit_config: Optional["BanditConfig"] = None,
        contextual_policy: Optional["ContextualBanditPolicy"] = None,
        ml_signal_filter: Optional["MLSignalFilter"] = None,
        ml_filter_enabled: bool = False,
        ml_filter_mode: str = "shadow",
        ml_shadow_threshold: Optional[float] = None,
        execution_adapter: Optional[Any] = None,
        telegram_notifier: Optional[Any] = None,
    ):
        """
        Initialize the signal handler.

        Args:
            state_manager: For reading/writing signal state
            performance_tracker: For tracking trade performance
            notification_queue: For sending Telegram notifications
            order_manager: For position sizing
            trading_circuit_breaker: Optional circuit breaker for risk management
            bandit_policy: Optional bandit policy for learning
            bandit_config: Optional bandit configuration
            contextual_policy: Optional contextual bandit for context-aware learning
            ml_signal_filter: Optional ML filter for predictions
            ml_filter_enabled: Whether ML filter is enabled
            ml_filter_mode: ML filter mode ('shadow' or 'live')
            ml_shadow_threshold: Optional shadow threshold for ML filter
            execution_adapter: Optional execution adapter for order placement
            telegram_notifier: Optional Telegram notifier
        """
        self.state_manager = state_manager
        self.performance_tracker = performance_tracker
        self.notification_queue = notification_queue
        self.order_manager = order_manager

        # Circuit breaker
        self.trading_circuit_breaker = trading_circuit_breaker

        # Learning components
        self.bandit_policy = bandit_policy
        self._bandit_config = bandit_config
        self.contextual_policy = contextual_policy

        # ML filter
        self._ml_signal_filter = ml_signal_filter
        self._ml_filter_enabled = ml_filter_enabled
        self._ml_filter_mode = ml_filter_mode
        self._ml_shadow_threshold = ml_shadow_threshold

        # Execution
        self.execution_adapter = execution_adapter
        self.telegram_notifier = telegram_notifier

        # Tracking
        self.signal_count = 0
        self.signals_sent = 0
        self.signals_send_failures = 0
        self.error_count = 0
        self.last_signal_generated_at: Optional[str] = None
        self.last_signal_sent_at: Optional[str] = None
        self.last_signal_send_error: Optional[str] = None
        self.last_signal_id_prefix: Optional[str] = None

        # For contextual learning
        self._context_features_class: Optional[type] = None
        try:
            from pearlalgo.learning.contextual_bandit import ContextFeatures
            self._context_features_class = ContextFeatures
        except ImportError:
            pass

    def configure_ml_filter(
        self,
        ml_signal_filter: Optional["MLSignalFilter"],
        enabled: bool = False,
        mode: str = "shadow",
        shadow_threshold: Optional[float] = None,
    ) -> None:
        """Configure ML filter settings."""
        self._ml_signal_filter = ml_signal_filter
        self._ml_filter_enabled = enabled
        self._ml_filter_mode = mode
        self._ml_shadow_threshold = shadow_threshold

    async def process_signal(
        self,
        signal: Dict,
        buffer_data: Optional[pd.DataFrame] = None,
    ) -> None:
        """
        Process a trading signal through the full pipeline.

        Args:
            signal: Signal dictionary
            buffer_data: Optional DataFrame with OHLCV data for chart generation
        """
        from pearlalgo.market_agent.notification_queue import Priority

        try:
            # ==========================================================================
            # TRADING CIRCUIT BREAKER: Check if signal should be allowed
            # ==========================================================================
            if not self._check_circuit_breaker(signal, buffer_data):
                return  # Signal blocked by circuit breaker

            # ==========================================================================
            # ML FILTER (shadow): attach prediction for later analytics/lift measurement
            # ==========================================================================
            self._apply_ml_filter(signal)

            # ==========================================================================
            # ML OPPORTUNITY SIZING (shadow-safe): adjust size/priority within risk gates
            # ==========================================================================
            try:
                self.order_manager.apply_ml_opportunity_sizing(signal)
            except Exception as e:
                logger.debug(f"ML sizing adjustment failed (non-fatal): {e}")

            # Track signal generation
            signal_id = self.performance_tracker.track_signal_generated(signal)
            self.last_signal_generated_at = get_utc_timestamp()
            self.last_signal_id_prefix = str(signal_id)[:16]

            # Guard: reject signals with NaN or None entry_price
            raw_entry_price = signal.get("entry_price")
            if raw_entry_price is None:
                logger.warning(
                    f"Rejecting signal {str(signal_id)[:16]}: entry_price is None"
                )
                return
            try:
                _entry_val = float(raw_entry_price)
                if math.isnan(_entry_val):
                    logger.warning(
                        f"Rejecting signal {str(signal_id)[:16]}: entry_price is NaN"
                    )
                    return
            except (TypeError, ValueError):
                logger.warning(
                    f"Rejecting signal {str(signal_id)[:16]}: "
                    f"entry_price={raw_entry_price!r} is not a valid number"
                )
                return

            # Guard: reject signals with timestamps more than 5 minutes in the future
            _raw_ts = signal.get("timestamp") or signal.get("_timestamp")
            if _raw_ts is not None:
                try:
                    _sig_dt = datetime.fromisoformat(
                        str(_raw_ts).replace("Z", "+00:00")
                    )
                    _now_utc = datetime.now(timezone.utc)
                    _future_delta = (_sig_dt - _now_utc).total_seconds()
                    if _future_delta > 300:  # 5 minutes
                        logger.warning(
                            f"Rejecting signal {str(signal_id)[:16]}: timestamp "
                            f"{_raw_ts} is {_future_delta:.0f}s in the future "
                            f"(max allowed: 300s)"
                        )
                        return
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Could not parse signal timestamp {_raw_ts!r} for "
                        f"signal {str(signal_id)[:16]}: {e}"
                    )

            # Virtual entry: enter immediately at the signal's entry price
            entry_price = self._track_virtual_entry(signal, signal_id)

            # ==========================================================================
            # BANDIT POLICY: Evaluate signal type and decide whether to execute
            # ==========================================================================
            policy_decision = self._apply_bandit_policy(signal)

            # ==========================================================================
            # CONTEXTUAL POLICY (optional): learn by session/regime/time bucket
            # ==========================================================================
            self._apply_contextual_policy(signal)

            # ==========================================================================
            # EXECUTION: Place bracket order if execution adapter is enabled + armed
            # ==========================================================================
            await self._execute_signal(signal, policy_decision)

            # Queue entry alert to Telegram (non-blocking)
            await self._queue_entry_notification(signal, signal_id, entry_price, buffer_data)

            self.signal_count += 1

        except Exception as e:
            logger.error(f"Error processing signal: {e}", exc_info=True)
            self.error_count += 1

    def _check_circuit_breaker(
        self,
        signal: Dict,
        buffer_data: Optional[pd.DataFrame],
    ) -> bool:
        """
        Check circuit breaker and return True if signal should proceed.

        Returns:
            True if signal should be processed, False if blocked
        """
        from pearlalgo.market_agent.notification_queue import Priority

        if self.trading_circuit_breaker is None:
            return True

        # Get active positions for clustering check
        active_positions = []
        try:
            recent_signals = self.state_manager.get_recent_signals(limit=100)
            for rec in recent_signals:
                if isinstance(rec, dict) and rec.get("status") == "entered":
                    active_positions.append(rec)
        except Exception:
            pass

        # Get market data for volatility filter
        market_data = {}
        if buffer_data is not None and len(buffer_data) > 0:
            try:
                from pearlalgo.trading_bots.pearl_bot_auto import calculate_atr
                atr_series = calculate_atr(buffer_data, period=14)
                if len(atr_series) > 20:
                    atr_current = float(atr_series.iloc[-1])
                    atr_average = float(atr_series.iloc[-20:].mean())
                    market_data = {
                        "atr_current": atr_current,
                        "atr_average": atr_average,
                    }
            except Exception:
                pass

        # Check if signal should be allowed
        cb_decision = self.trading_circuit_breaker.should_allow_signal(
            signal=signal,
            active_positions=active_positions,
            market_data=market_data,
        )

        if not cb_decision.allowed:
            signal.setdefault("_risk_warnings", []).append(cb_decision.to_dict())

            cb_mode = str(getattr(self.trading_circuit_breaker.config, "mode", "enforce"))
            if cb_mode == "warn_only":
                self.trading_circuit_breaker.record_would_block(cb_decision.reason)
                logger.warning(
                    f"⚠️ Trading circuit breaker would block (warn-only): {cb_decision.reason} | "
                    f"details={cb_decision.details}"
                )
                if cb_decision.severity == "critical":
                    asyncio.create_task(
                        self.notification_queue.enqueue_circuit_breaker(
                            f"Risk warning (warn-only): {cb_decision.reason}",
                            cb_decision.details,
                            priority=Priority.HIGH,
                        )
                    )
                return True  # Allow in warn-only mode
            else:
                logger.warning(
                    f"🛑 Trading circuit breaker blocked signal: {cb_decision.reason} | "
                    f"details={cb_decision.details}"
                )
                if cb_decision.severity == "critical":
                    asyncio.create_task(
                        self.notification_queue.enqueue_circuit_breaker(
                            f"Trading paused: {cb_decision.reason}",
                            cb_decision.details,
                            priority=Priority.HIGH,
                        )
                    )
                return False  # Block in enforce mode

        return True

    def _apply_ml_filter(self, signal: Dict) -> None:
        """Apply ML filter prediction (shadow mode - never blocks)."""
        try:
            if not self._ml_filter_enabled or self._ml_signal_filter is None:
                return

            ctx: Dict[str, Any] = {}
            # Best-effort regime mapping
            try:
                mr = signal.get("market_regime") or {}
                if isinstance(mr, dict):
                    regime_type = str(mr.get("regime") or "")
                    vol_bucket = ""
                    try:
                        vr = mr.get("volatility_ratio")
                        if vr is not None:
                            v = float(vr)
                            if v < 0.8:
                                vol_bucket = "low"
                            elif v > 1.5:
                                vol_bucket = "high"
                            else:
                                vol_bucket = "normal"
                    except Exception:
                        vol_bucket = ""
                    ctx["regime"] = {
                        "regime": regime_type,
                        "volatility": vol_bucket,
                        "session": str(mr.get("session") or ""),
                    }
            except Exception:
                ctx = {}

            _should_exec, pred = self._ml_signal_filter.should_execute(signal, ctx)
            try:
                signal["_ml_prediction"] = pred.to_dict()
                pass_for_lift = bool(_should_exec)
                try:
                    if (
                        self._ml_filter_mode == "shadow"
                        and self._ml_shadow_threshold is not None
                    ):
                        pass_for_lift = float(getattr(pred, "win_probability", 0.0) or 0.0) >= float(
                            self._ml_shadow_threshold
                        )
                        signal["_ml_shadow_threshold"] = float(self._ml_shadow_threshold)
                except Exception:
                    pass_for_lift = bool(_should_exec)
                signal["_ml_shadow_pass_filter"] = bool(pass_for_lift)
            except Exception:
                signal["_ml_prediction"] = None
        except Exception as e:
            logger.debug(f"ML prediction failed (non-fatal): {e}")

    def _track_virtual_entry(self, signal: Dict, signal_id: str) -> float:
        """Track virtual entry for the signal. Returns entry price."""
        entry_price = 0.0
        try:
            entry_price = float(signal.get("entry_price") or 0.0)
            signal_direction = signal.get("direction", "unknown")
            if entry_price > 0:
                logger.info(
                    f"🔍 VIRTUAL ENTRY: signal_id={signal_id[:16]} | direction={signal_direction.upper()} | "
                    f"entry={entry_price:.2f} | stop={signal.get('stop_loss', 'N/A')} | "
                    f"target={signal.get('take_profit', 'N/A')}"
                )
                self.performance_tracker.track_entry(
                    signal_id=signal_id,
                    entry_price=entry_price,
                    entry_time=datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning(f"Critical path error: {e}", exc_info=True)
        return entry_price

    def _apply_bandit_policy(self, signal: Dict) -> Optional[Any]:
        """Apply bandit policy decision. Returns policy decision if available."""
        policy_decision = None
        policy_status = "not_evaluated"

        if self.bandit_policy is not None:
            try:
                policy_decision = self.bandit_policy.decide(signal)
                policy_status = f"{policy_decision.mode}:{policy_decision.reason}"

                logger.info(
                    f"Policy decision: {signal.get('type')} -> "
                    f"execute={policy_decision.execute} | "
                    f"score={policy_decision.sampled_score:.2f} | "
                    f"mode={policy_decision.mode}"
                )
            except Exception as policy_e:
                policy_status = f"error:{str(policy_e)[:50]}"
                logger.error(f"Policy evaluation error: {policy_e}", exc_info=True)

        signal["_policy_status"] = policy_status
        if policy_decision:
            try:
                signal["_policy"] = policy_decision.to_dict()
            except Exception:
                signal["_policy"] = None
            signal["_policy_execute"] = policy_decision.execute
            signal["_policy_score"] = policy_decision.sampled_score
            signal["_policy_size_multiplier"] = policy_decision.size_multiplier

        return policy_decision

    def _apply_contextual_policy(self, signal: Dict) -> None:
        """Apply contextual policy decision."""
        if self.contextual_policy is None:
            return

        try:
            ctx_features = self._build_context_features_for_signal(signal)
            if ctx_features is not None:
                ctx_decision = self.contextual_policy.decide(signal, ctx_features)
                try:
                    signal["_context_features"] = ctx_features.to_dict()
                except Exception:
                    signal["_context_features"] = None
                try:
                    signal["_policy_ctx"] = ctx_decision.to_dict()
                except Exception:
                    signal["_policy_ctx"] = None
        except Exception as e:
            signal["_policy_ctx"] = {"error": str(e)[:120]}

    def _build_context_features_for_signal(self, signal: Dict) -> Optional[Any]:
        """Build context features for contextual bandit."""
        if self._context_features_class is None:
            return None

        try:
            # Extract context from signal
            session = "unknown"
            regime = "unknown"
            time_bucket = "unknown"

            # Try to get session from signal
            try:
                session = str(signal.get("_session") or signal.get("session") or "unknown")
            except Exception:
                pass

            # Try to get regime from signal
            try:
                mr = signal.get("market_regime") or {}
                if isinstance(mr, dict):
                    regime = str(mr.get("regime") or "unknown")
            except Exception:
                pass

            # Try to get time bucket from signal
            try:
                ts = signal.get("timestamp") or signal.get("_timestamp")
                if ts:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    hour = dt.hour
                    if hour < 10:
                        time_bucket = "morning"
                    elif hour < 14:
                        time_bucket = "midday"
                    else:
                        time_bucket = "afternoon"
            except Exception:
                pass

            return self._context_features_class(
                session=session,
                regime=regime,
                time_bucket=time_bucket,
            )
        except Exception as e:
            logger.debug(f"Could not build context features: {e}")
            return None

    async def _execute_signal(self, signal: Dict, policy_decision: Optional[Any]) -> None:
        """Execute signal via execution adapter if enabled."""
        execution_result = None
        execution_status = "not_attempted"

        # Gate execution by policy decision (only in live mode)
        should_execute = True
        if (policy_decision is not None
            and self._bandit_config is not None
            and self._bandit_config.mode == "live"):
            should_execute = policy_decision.execute
            if not should_execute:
                execution_status = f"policy_skip:{policy_decision.reason}"
                logger.info(f"Execution blocked by policy (live mode): {policy_decision.reason}")

        if should_execute and self.execution_adapter is not None:
            try:
                # Check preconditions
                decision = self.execution_adapter.check_preconditions(signal)

                if decision.execute:
                    # Apply size multiplier from policy
                    if (policy_decision is not None
                        and self._bandit_config is not None
                        and self._bandit_config.mode == "live"):
                        original_size = signal.get("position_size", 1)
                        adjusted_size = int(original_size * policy_decision.size_multiplier)
                        adjusted_size = max(1, adjusted_size)
                        signal["position_size"] = adjusted_size
                        logger.info(
                            f"Position size adjusted by policy: {original_size} -> {adjusted_size} "
                            f"(multiplier={policy_decision.size_multiplier})"
                        )

                    # Place bracket order
                    execution_result = await self.execution_adapter.place_bracket(signal)

                    if execution_result.success:
                        execution_status = "placed"
                        logger.info(
                            f"✅ Order placed: {signal.get('type')} {signal.get('direction')} | "
                            f"order_id={execution_result.parent_order_id}"
                        )
                    else:
                        execution_status = f"place_failed:{execution_result.error_message}"
                        logger.warning(f"⚠️ Order placement failed: {execution_result.error_message}")
                else:
                    execution_status = f"skipped:{decision.reason}"
                    logger.info(f"Order skipped: {decision.reason} | signal_id={signal.get('signal_id', '')[:16]}")

            except Exception as exec_e:
                execution_status = f"error:{str(exec_e)[:50]}"
                logger.error(f"Execution error: {exec_e}", exc_info=True)

        signal["_execution_status"] = execution_status
        if execution_result:
            signal["_execution_order_id"] = execution_result.parent_order_id

    async def _queue_entry_notification(
        self,
        signal: Dict,
        signal_id: str,
        entry_price: float,
        buffer_data: Optional[pd.DataFrame],
    ) -> None:
        """Queue entry notification to Telegram."""
        from pearlalgo.market_agent.notification_queue import Priority

        signal_type = signal.get('type', 'unknown')
        signal_direction = signal.get('direction', 'unknown')
        logger.info(f"Processing signal: {signal_type} {signal_direction}")

        entry_priority = Priority.HIGH
        try:
            if bool(signal.get("_ml_priority") == "critical"):
                entry_priority = Priority.CRITICAL
        except Exception:
            entry_priority = Priority.HIGH

        queued = await self.notification_queue.enqueue_entry(
            signal_id=str(signal_id),
            entry_price=float(entry_price),
            signal=signal,
            buffer_data=buffer_data,
            priority=entry_priority,
        )

        if queued:
            logger.info(f"✅ Entry queued for Telegram: {signal_type} {signal_direction}")
            self.signals_sent += 1
            self.last_signal_sent_at = get_utc_timestamp()
            self.last_signal_send_error = None
        else:
            logger.error(
                f"❌ Failed to queue entry to Telegram (queue full): {signal_type} {signal_direction}. "
                f"Telegram enabled: {self.telegram_notifier.enabled if self.telegram_notifier else 'N/A'}"
            )
            self.signals_send_failures += 1
            self.last_signal_send_error = "Notification queue full - entry dropped"

    def get_stats(self) -> Dict[str, Any]:
        """Return signal handler statistics."""
        return {
            "signal_count": self.signal_count,
            "signals_sent": self.signals_sent,
            "signals_send_failures": self.signals_send_failures,
            "error_count": self.error_count,
            "last_signal_generated_at": self.last_signal_generated_at,
            "last_signal_sent_at": self.last_signal_sent_at,
            "last_signal_send_error": self.last_signal_send_error,
            "last_signal_id_prefix": self.last_signal_id_prefix,
        }
