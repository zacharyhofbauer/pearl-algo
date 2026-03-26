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
import pytz

from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

_ET = pytz.timezone("America/New_York")

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
        audit_logger: Optional[Any] = None,
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
            audit_logger: Optional AuditLogger for persistent audit events
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

        # Audit
        self._audit_logger = audit_logger

        # Execution serialization semaphore — prevents signal storms.
        # follower_execute acquires this before executing; queued signals
        # re-check position limits when their turn comes.
        self._execution_semaphore: asyncio.Semaphore = asyncio.Semaphore(1)

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

    def _is_signal_type_allowed(self, signal: Dict) -> bool:
        """
        Check if the signal type is in the enabled whitelist.

        Reads signals.enabled_signal_types from config. If the list is
        non-empty, only signals whose 'type' field matches an entry are
        allowed. Unknown or missing types are rejected (secure-by-default).

        Returns:
            True if signal type is allowed, False otherwise.
        """
        try:
            from pearlalgo.config.config_loader import load_config_yaml
            cfg = load_config_yaml()
            signals_cfg = cfg.get("signals", {}) or {}
            whitelist = signals_cfg.get("enabled_signal_types", None)
        except Exception as e:
            logger.debug("_is_signal_type_allowed: config load failed, allowing: %s", e)
            return True

        if not whitelist:
            return True  # No whitelist configured = allow all

        signal_type = str(signal.get("type", "")).strip()
        if not signal_type:
            logger.warning(
                "Signal rejected: missing 'type' field (whitelist active: %s)", whitelist
            )
            return False

        if signal_type not in whitelist:
            logger.warning(
                "Signal rejected: type '%s' not in enabled_signal_types %s",
                signal_type, whitelist,
            )
            return False

        return True

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
            # SIGNAL TYPE GATE: Reject signals not in the enabled whitelist
            # ==========================================================================
            if not self._is_signal_type_allowed(signal):
                return  # Signal type not whitelisted

            # ==========================================================================
            # TRADING CIRCUIT BREAKER: Check if signal should be allowed
            # ==========================================================================
            if not self._check_circuit_breaker(signal, buffer_data):
                return  # Signal blocked by circuit breaker

            # ==========================================================================
            # POSITION SIZING: Compute position size if not already set
            # ==========================================================================
            self._ensure_position_size(signal)

            # ==========================================================================
            # ML FILTER (shadow): attach prediction for later analytics/lift measurement
            # ==========================================================================
            await self._apply_ml_filter(signal)

            # ==========================================================================
            # ML OPPORTUNITY SIZING (shadow-safe): adjust size/priority within risk gates
            # ==========================================================================
            try:
                self.order_manager.apply_ml_opportunity_sizing(signal)
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "ML opportunity sizing adjustment", e, category="ml_filter",
                )

            # Track signal generation
            signal_id = self.performance_tracker.track_signal_generated(signal)
            self.last_signal_generated_at = get_utc_timestamp()
            self.last_signal_id_prefix = str(signal_id)[:16]

            # Guard: reject signals with invalid entry_price
            validated_price = self._validate_entry_price(signal, signal_id)
            if validated_price is None:
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
            entry_price = self._track_virtual_entry(signal, signal_id, preserve_full_signal=True)

            # Audit: trade entered
            self._log_trade_entry(signal_id, signal, entry_price, "virtual")

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

    async def follower_execute(self, signal: Dict) -> None:
        """Streamlined execution path for signal forwarding (Tradovate Paper follower).

        Skips ML filter, bandit policy, and contextual policy since these are
        IBKR Virtual-specific. Only runs: circuit breaker -> position sizing ->
        tracking -> virtual entry -> execution -> notification.

        Serialized via _execution_semaphore to prevent signal storms: concurrent
        signals queue here and re-check position limits after acquiring the lock,
        so the circuit breaker sees real broker position state on each attempt.

        Args:
            signal: Signal dictionary from strategy or forwarded source
        """
        async with self._execution_semaphore:
            try:
                # Circuit breaker check (re-evaluated inside semaphore so each
                # queued signal sees current position state, not stale snapshot
                # from before prior signals were recorded).
                if not self._check_circuit_breaker(signal, None):
                    return

                # Position sizing: compute if not already set
                self._ensure_position_size(signal)

                # Track signal generation
                signal_id = self.performance_tracker.track_signal_generated(signal)
                self.last_signal_generated_at = get_utc_timestamp()
                self.last_signal_id_prefix = str(signal_id)[:16]

                # Guard: entry price validation
                validated_price = self._validate_entry_price(signal, signal_id)
                if validated_price is None:
                    return

                # Execute first — only record virtual entry if Tradovate confirms placement.
                # Previously virtual entry was recorded before execution, causing trades.db
                # to fill with phantom entries even when broker rejected the order.
                await self._execute_signal(signal, policy_decision=None)

                execution_status = signal.get("_execution_status", "")
                if execution_status != "placed":
                    logger.info(
                        f"follower_execute: skipping virtual entry record — "
                        f"execution_status={execution_status!r} (not placed)"
                    )
                    return

                # Virtual entry — only reached if broker confirmed placement
                entry_price = self._track_virtual_entry(signal, signal_id)

                # Audit: trade entered
                self._log_trade_entry(signal_id, signal, entry_price, "follower")

                # Queue notification
                await self._queue_entry_notification(signal, signal_id, entry_price, buffer_data=None)

                self.signal_count += 1

            except Exception as e:
                logger.error(f"Error in follower_execute: {e}", exc_info=True)
                self.error_count += 1

    # ------------------------------------------------------------------
    # Shared helpers (eliminate duplication between process_signal & follower_execute)
    # ------------------------------------------------------------------

    def _get_scaled_contracts(self, signal: dict) -> int:
        """
        Confidence-based contract scaling. GATED: only active when
        confidence_scaling.enabled = True in config.
        # ADDED 2026-03-25: confidence scaling
        """
        base = 1  # always safe default

        try:
            from pearlalgo.config.config_loader import load_config_yaml
            cfg = load_config_yaml()
            cs = cfg.get("confidence_scaling", {}) or {}
        except Exception as e:
            logger.debug(f"_get_scaled_contracts: config load failed, returning base: {e}")
            return base

        if not cs.get("enabled", False):
            return base

        confidence = float(signal.get("confidence", 0) or 0)
        direction = signal.get("direction", "long") or "long"

        # long_only_scaling: don't scale shorts until edge is proven
        if cs.get("long_only_scaling", True) and direction != "long":
            return base

        # Walk tiers, find matching
        contracts = base
        tiers = cs.get("tiers", []) or []
        for tier in tiers:
            try:
                if tier["min_confidence"] <= confidence <= tier["max_confidence"]:
                    contracts = int(tier["contracts"])
                    break
            except (KeyError, TypeError):
                continue

        # Never exceed hard ceiling or MFF max (5)
        max_c = min(int(cs.get("max_contracts", 3) or 3), 5)
        result = min(contracts, max_c)
        if result != base:
            logger.info(
                f"_get_scaled_contracts: confidence={confidence:.3f} direction={direction} -> {result} contracts"
                " # ADDED 2026-03-25: confidence scaling"
            )
        return result

    def _ensure_position_size(self, signal: Dict) -> None:
        """Compute and set position_size on the signal if not already present.

        Delegates to ``OrderManager.compute_base_position_size()`` which uses
        strategy config (base_contracts, dynamic sizing, confidence thresholds)
        and risk limits (min/max position size) to determine the correct size.

        Without this step, signals from the strategy (which does not set
        position_size) would be rejected by the execution adapter's
        precondition check (``position_size <= 0``).
        """
        existing = signal.get("position_size")
        if existing is not None:
            if not isinstance(existing, int):
                logger.warning(
                    "position_size has unexpected type %s (value=%r); will recompute",
                    type(existing).__name__, existing,
                )
            elif existing > 0:
                return  # Already has a valid int size
            else:
                # existing is int but <= 0 (or invalid), fall through to compute
                pass

        try:
            size = self.order_manager.compute_base_position_size(signal)
            # ADDED 2026-03-25: confidence scaling
            scaled = self._get_scaled_contracts(signal)
            if scaled > size:
                size = scaled
            signal["position_size"] = size
            logger.debug(
                f"Position size computed: {size} contracts "
                f"(confidence={signal.get('confidence', 'N/A')})"
            )
        except Exception as e:
            # Fail closed: set 0 so execution adapter rejects as non_positive
            signal["position_size"] = 0
            logger.error(f"Position size computation failed, failing closed (position_size=0): {e}")

    def _validate_entry_price(self, signal: Dict, signal_id: Any) -> Optional[float]:
        """Validate entry_price from a signal dict.

        Returns the validated price as a float, or ``None`` if invalid
        (caller should ``return`` early).
        """
        sid = str(signal_id)[:16]
        raw = signal.get("entry_price")
        if raw is None:
            logger.warning(f"Rejecting signal {sid}: entry_price is None")
            if self._audit_logger is not None:
                self._audit_logger.log_signal_rejected(str(signal_id), "entry_price_none", {})
            return None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            logger.warning(f"Rejecting signal {sid}: entry_price={raw!r} is not a valid number")
            if self._audit_logger is not None:
                self._audit_logger.log_signal_rejected(str(signal_id), "entry_price_invalid", {"value": str(raw)})
            return None
        if math.isnan(val) or math.isinf(val):
            logger.warning(f"Rejecting signal {sid}: entry_price is NaN/Inf")
            if self._audit_logger is not None:
                self._audit_logger.log_signal_rejected(str(signal_id), "entry_price_nan", {})
            return None
        if val <= 0:
            logger.warning(f"Rejecting signal {sid}: entry_price={val} is <= 0")
            if self._audit_logger is not None:
                self._audit_logger.log_signal_rejected(str(signal_id), "entry_price_non_positive", {"value": str(val)})
            return None
        return val

    def _log_trade_entry(
        self, signal_id: Any, signal: Dict, entry_price: float, execution_status: str,
    ) -> None:
        """Log a trade entry to the audit logger (non-fatal on failure)."""
        if self._audit_logger is None:
            return
        try:
            self._audit_logger.log_trade_entered(
                str(signal_id),
                {
                    "entry_price": float(entry_price),
                    "direction": str(signal.get("direction", "")),
                    "position_size": int(signal.get("position_size", 1)),
                    "execution_status": execution_status,
                },
            )
        except Exception as exc:
            logger.warning(f"Audit log_trade_entered failed: {exc}")

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

        # Get active positions for clustering check.
        # signals.jsonl is append-only, so derive active positions from the
        # Use BROKER position cache as source of truth when available.
        # Falls back to virtual trades (signals.jsonl) only if broker data is unavailable.
        active_positions = []
        try:
            broker_positions = None
            if self.execution_adapter is not None:
                # Use the cached _live_positions (sync, no await needed)
                live_pos = getattr(self.execution_adapter, "_live_positions", None)
                if live_pos is not None:
                    broker_positions = list(live_pos.values())

            if broker_positions:
                # Use broker data — each position with net_pos != 0 counts
                for pos in broker_positions:
                    net_pos = pos.get("netPos") or pos.get("net_pos") or 0
                    if net_pos != 0:
                        active_positions.append({
                            "direction": "long" if net_pos > 0 else "short",
                            "entry_price": pos.get("netPrice") or pos.get("net_price") or 0,
                            "position_size": abs(net_pos),
                        })
            else:
                # Fallback: virtual trades from signals.jsonl
                recent_signals = self.state_manager.get_recent_signals(limit=300)
                latest_by_id: Dict[str, Dict[str, Any]] = {}
                for rec in recent_signals:
                    if not isinstance(rec, dict):
                        continue
                    sig_id = str(rec.get("signal_id") or "")
                    if not sig_id:
                        continue
                    latest_by_id[sig_id] = rec

                for rec in latest_by_id.values():
                    if rec.get("status") == "entered":
                        active_positions.append(rec)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "circuit_breaker active positions fetch", e,
                level="warning", category="circuit_breaker",
            )

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
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "circuit_breaker ATR calculation", e, category="circuit_breaker",
                )

        # Check if signal should be allowed
        cb_decision = self.trading_circuit_breaker.should_allow_signal(
            signal=signal,
            active_positions=active_positions,
            market_data=market_data,
        )

        if not cb_decision.allowed:
            signal.setdefault("_risk_warnings", []).append(cb_decision.to_dict())

            cb_mode = str(getattr(self.trading_circuit_breaker.config, "mode", "enforce"))
            if cb_mode in ("warn_only", "shadow"):
                self.trading_circuit_breaker.record_would_block(cb_decision.reason)
                logger.warning(
                    f"⚠️ Trading circuit breaker would block (warn-only): {cb_decision.reason} | "
                    f"details={cb_decision.details}"
                )
                # Don't send to Telegram in warn_only — we're still allowing the trade, so no action needed; avoids spam.
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
                # Audit: signal rejected by circuit breaker
                if self._audit_logger is not None:
                    self._audit_logger.log_signal_rejected(
                        str(signal.get("signal_id", "")),
                        f"circuit_breaker:{cb_decision.reason}",
                        cb_decision.details or {},
                    )
                return False  # Block in enforce mode

        return True

    async def _apply_ml_filter(self, signal: Dict) -> None:
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
                    except Exception as e:
                        ErrorHandler.log_and_continue(
                            "ML filter volatility bucket", e, category="ml_filter",
                        )
                        vol_bucket = ""
                    ctx["regime"] = {
                        "regime": regime_type,
                        "volatility": vol_bucket,
                        "session": str(mr.get("session") or ""),
                    }
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "ML filter regime mapping", e, category="ml_filter",
                )
                ctx = {}

            _should_exec, pred = await self._ml_signal_filter.should_execute_async(signal, ctx)
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
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "ML shadow threshold evaluation", e, category="ml_filter",
                    )
                    pass_for_lift = bool(_should_exec)
                signal["_ml_shadow_pass_filter"] = bool(pass_for_lift)
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "ML prediction serialization", e, category="ml_filter",
                )
                signal["_ml_prediction"] = None
        except Exception as e:
            ErrorHandler.log_and_continue(
                "ML prediction (non-fatal)", e, category="ml_filter",
            )

    def _track_virtual_entry(self, signal: Dict, signal_id: str, preserve_full_signal: bool = False) -> float:
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
                    entry_time=datetime.now(_ET).replace(tzinfo=None),  # FIXED 2026-03-25: naive ET
                    signal_data=signal if preserve_full_signal else None,
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
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "bandit policy serialization", e, category="ml_filter",
                )
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
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "contextual features serialization", e, category="ml_filter",
                    )
                    signal["_context_features"] = None
                try:
                    signal["_policy_ctx"] = ctx_decision.to_dict()
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "contextual policy serialization", e, category="ml_filter",
                    )
                    signal["_policy_ctx"] = None
        except Exception as e:
            ErrorHandler.log_and_continue(
                "contextual policy evaluation", e, level="warning", category="ml_filter",
            )
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
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "context features session extraction", e, category="ml_filter",
                )

            # Try to get regime from signal
            try:
                mr = signal.get("market_regime") or {}
                if isinstance(mr, dict):
                    regime = str(mr.get("regime") or "unknown")
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "context features regime extraction", e, category="ml_filter",
                )

            # Try to get time bucket from signal
            try:
                ts = signal.get("timestamp") or signal.get("_timestamp")
                if ts:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace("+00:00", ""))
                    hour = dt.hour  # FIXED 2026-03-25: hour is now ET natively
                    if hour < 10:
                        time_bucket = "morning"
                    elif hour < 14:
                        time_bucket = "midday"
                    else:
                        time_bucket = "afternoon"
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "context features time bucket extraction", e, category="ml_filter",
                )

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
                guard_ok = await self._enforce_tradovate_protection_guard(signal)
                if not guard_ok:
                    execution_status = "skipped:unprotected_open_position_auto_disarm"
                    signal.setdefault("_risk_warnings", []).append({
                        "allowed": False,
                        "reason": "unprotected_open_position",
                        "severity": "critical",
                        "details": {
                            "message": "Open position detected with no working protective orders; execution auto-disarmed",
                        },
                    })
                    signal["_execution_status"] = execution_status
                    return

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
                        # FIXED 2026-03-25: warn if order_id is None (bracket may be missing)
                        if execution_result.parent_order_id:
                            execution_status = "placed"
                            logger.info(
                                f"✅ Order placed: {signal.get('type')} {signal.get('direction')} | "
                                f"order_id={execution_result.parent_order_id}"
                            )
                        else:
                            execution_status = "placed_no_id"
                            logger.warning(
                                f"⚠️ Order entry filled but bracket MISSING: {signal.get('type')} {signal.get('direction')} | "
                                f"order_id=None — Tradovate did not return an order ID"
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

    async def _enforce_tradovate_protection_guard(self, signal: Dict) -> bool:
        """
        Hard safety brake: if Tradovate reports an open position with no working
        protective orders, disarm execution and block new entries.

        Returns:
            True if execution may proceed, False if blocked by safety guard.
        """
        adapter = self.execution_adapter
        if adapter is None or not hasattr(adapter, "get_account_summary"):
            return True

        try:
            summary = await adapter.get_account_summary()
            if not isinstance(summary, dict):
                return True

            positions = summary.get("positions") or []
            open_positions = []
            for p in positions:
                try:
                    if abs(float(p.get("net_pos", 0) or 0)) > 0:
                        open_positions.append(p)
                except (TypeError, ValueError):
                    continue

            if not open_positions:
                return True

            working_orders = summary.get("working_orders") or []
            valid_working = []
            for o in working_orders:
                try:
                    qty = float(o.get("qty", 0) or 0)
                except (TypeError, ValueError):
                    qty = 0.0
                has_price = o.get("price") is not None or o.get("stop_price") is not None
                has_type = bool(str(o.get("order_type", "") or "").strip())
                if qty > 0 and (has_price or has_type):
                    valid_working.append(o)

            if valid_working:
                return True

            # Default behavior is monitor/warn-only to avoid deadlocking execution
            # when broker telemetry briefly reports incomplete order details.
            # Optional strict mode can be enabled by setting
            # execution.enforce_protection_guard=true on adapter config.
            enforce_guard = bool(
                getattr(getattr(adapter, "config", None), "enforce_protection_guard", False)
            )
            logger.warning(
                f"🔍 PROTECTION GUARD DEBUG: adapter.config exists={adapter.config is not None}, "
                f"enforce_guard={enforce_guard}, "
                f"config.enforce_protection_guard={getattr(adapter.config, 'enforce_protection_guard', 'MISSING')}"
            )
            if enforce_guard:
                if hasattr(adapter, "disarm"):
                    adapter.disarm()
                logger.error(
                    "🚨 AUTO-DISARM SAFETY BRAKE (STRICT): open Tradovate position with "
                    "no valid working protective orders; blocking new entries | signal_id=%s",
                    str(signal.get("signal_id", ""))[:16],
                )
                return False

            logger.error(
                "⚠️ PROTECTION GUARD WARNING: open Tradovate position with no valid "
                "working protective orders; monitor-only mode allows entries | signal_id=%s",
                str(signal.get("signal_id", ""))[:16],
            )
            return True

        except Exception as e:
            # Non-fatal: do not block execution solely due to telemetry failure.
            logger.warning(f"Protective-order safety guard check failed (non-fatal): {e}")
            return True

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
        except Exception as e:
            ErrorHandler.log_and_continue(
                "entry notification priority check", e, category="ml_filter",
            )
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
