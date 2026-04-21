"""
Order Manager Module

Handles position sizing and order-related calculations.
Extracted from service.py for better code organization.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from pearlalgo.config.defaults import (
    CONFIDENCE_HIGH_SIZE_MULTIPLIER,
    CONFIDENCE_LOW_SIZE_MULTIPLIER,
    CONFIDENCE_MEDIUM_SIZE_MULTIPLIER,
    CONFIDENCE_MEDIUM_THRESHOLD,
    DEFAULT_MARGIN_PER_CONTRACT,
)
from pearlalgo.utils.config_helpers import safe_get_bool, safe_get_float, safe_get_int
from pearlalgo.utils.logger import logger

_DEFAULT_MARGIN_PER_CONTRACT = DEFAULT_MARGIN_PER_CONTRACT


class OrderManager:
    """
    Manages order sizing and related calculations.

    Responsibilities:
    - Base position size calculation
    - Risk-adjusted sizing
    """

    def __init__(
        self,
        risk_settings: Optional[Dict] = None,
        strategy_settings: Optional[Dict] = None,
    ):
        """
        Initialize the order manager.

        Args:
            risk_settings: Risk configuration (min/max position size, etc.)
            strategy_settings: Strategy configuration (dynamic sizing, etc.)
        """
        self._risk_settings = risk_settings or {}
        self._strategy_settings = strategy_settings or {}

    def validate_signal_financials(self, signal: Dict) -> bool:
        """
        Validate financial inputs in a signal before order sizing.

        Checks:
        - ``entry_price > 0``
        - ``stop_loss > 0``
        - For long signals: ``stop_loss < entry_price``
        - For short signals: ``stop_loss > entry_price``

        Args:
            signal: Signal dictionary (must include ``entry_price`` and
                ``stop_loss`` for full validation; missing values are
                treated as "not yet set" and pass).

        Returns:
            ``True`` if the signal passes validation (or has no price
            fields to validate), ``False`` otherwise.
        """
        entry_price = signal.get("entry_price")
        stop_loss = signal.get("stop_loss")

        # If neither price field is present, nothing to validate yet.
        if entry_price is None and stop_loss is None:
            return True

        try:
            entry_price = float(entry_price) if entry_price is not None else None
        except (TypeError, ValueError):
            logger.warning(
                "validate_signal_financials: entry_price is not numeric "
                f"(got {signal.get('entry_price')!r})"
            )
            return False

        try:
            stop_loss = float(stop_loss) if stop_loss is not None else None
        except (TypeError, ValueError):
            logger.warning(
                "validate_signal_financials: stop_loss is not numeric "
                f"(got {signal.get('stop_loss')!r})"
            )
            return False

        if entry_price is not None and entry_price <= 0:
            logger.warning(
                f"validate_signal_financials: entry_price must be > 0 (got {entry_price})"
            )
            return False

        if stop_loss is not None and stop_loss <= 0:
            logger.warning(
                f"validate_signal_financials: stop_loss must be > 0 (got {stop_loss})"
            )
            return False

        # Direction-aware stop-loss check
        if entry_price is not None and stop_loss is not None:
            direction = str(signal.get("direction") or signal.get("side") or "").lower()
            if direction in ("long", "buy"):
                if stop_loss >= entry_price:
                    logger.warning(
                        "validate_signal_financials: long signal stop_loss "
                        f"({stop_loss}) must be < entry_price ({entry_price})"
                    )
                    return False
            elif direction in ("short", "sell"):
                if stop_loss <= entry_price:
                    logger.warning(
                        "validate_signal_financials: short signal stop_loss "
                        f"({stop_loss}) must be > entry_price ({entry_price})"
                    )
                    return False

        return True

    def compute_base_position_size(self, signal: Dict) -> int:
        """
        Compute a base position size from config + signal confidence.

        Args:
            signal: Signal dictionary with optional confidence score

        Returns:
            Position size (number of contracts).  Returns the configured
            minimum (at least 1) when financial-input validation fails.
        """
        # --- Financial input validation (WS6) ---
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
        except Exception:
            min_size = 1
        safe_default = max(1, min_size)

        if not self.validate_signal_financials(signal):
            logger.warning(
                "compute_base_position_size: returning safe default "
                f"({safe_default}) due to failed financial validation"
            )
            return safe_default

        # Check if signal already has a size
        existing = signal.get("position_size")
        if existing is not None:
            parsed = safe_get_int({"_v": existing}, "_v", 0, warn=True, context="order_manager")
            if parsed > 0:
                return max(1, parsed)

        cfg = self._strategy_settings or {}
        enable_dynamic = safe_get_bool(cfg, "enable_dynamic_sizing", False, context="order_manager")
        base_contracts = safe_get_int(cfg, "base_contracts", 1, context="order_manager")
        high_contracts = safe_get_int(cfg, "high_conf_contracts", base_contracts, context="order_manager")
        max_contracts = safe_get_int(cfg, "max_conf_contracts", high_contracts, context="order_manager")

        # Get confidence from signal
        conf = safe_get_float({"_v": signal.get("confidence")}, "_v", 0.0, warn=False)

        # Get thresholds
        high_th = safe_get_float(cfg, "high_conf_threshold", 0.8, context="order_manager")
        max_th = safe_get_float(cfg, "max_conf_threshold", 0.9, context="order_manager")

        # Determine size based on confidence
        size = base_contracts
        if enable_dynamic:
            if conf >= max_th:
                size = max_contracts
            elif conf >= high_th:
                size = high_contracts
            else:
                size = base_contracts

        # Apply per-signal-type sizing multiplier
        try:
            multipliers = cfg.get("signal_type_size_multipliers", {}) or {}
            sig_type = str(signal.get("type") or "")
            if sig_type in multipliers:
                size = int(round(size * float(multipliers.get(sig_type) or 1.0)))
        except (TypeError, ValueError) as e:
            logger.debug("Order manager: signal_type_size_multipliers parse failed: %s", e)

        # Clamp to risk min/max
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
        except (TypeError, ValueError) as e:
            logger.debug("Order manager: min_position_size parse failed, using 1: %s", e)
            min_size = 1
        try:
            max_size = int(self._risk_settings.get("max_position_size", size) or size)
        except (TypeError, ValueError) as e:
            logger.debug("Order manager: max_position_size parse failed, using size: %s", e)
            max_size = size

        size = max(min_size, min(max_size, size))
        return max(1, size)

    def validate_position_size(
        self,
        size: int,
        *,
        direction: str = "long",
        account_value: Optional[float] = None,
        current_exposure: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Validate a position size against risk limits.

        Args:
            size: Proposed position size
            direction: Trade direction ('long' or 'short')
            account_value: Optional account value for percentage checks
            current_exposure: Optional current exposure

        Returns:
            Dictionary with:
            - valid: bool
            - adjusted_size: int (may be reduced)
            - reason: str (if invalid or adjusted)
        """
        result: Dict[str, Any] = {
            "valid": True,
            "adjusted_size": size,
            "reason": None,
        }

        # Check minimum (fail-safe: reject if config unreadable)
        try:
            min_size = int(self._risk_settings.get("min_position_size", 1) or 1)
            if size < min_size:
                result["valid"] = False
                result["reason"] = f"Size {size} below minimum {min_size}"
                return result
        except (TypeError, ValueError) as e:
            logger.warning("Order manager: could not read min_position_size (rejecting order): %s", e)
            result["valid"] = False
            result["reason"] = "Configuration error: min position size invalid"
            return result

        # Check maximum (fail-safe: reject if config unreadable)
        try:
            max_size = int(self._risk_settings.get("max_position_size", 999) or 999)
            if size > max_size:
                result["adjusted_size"] = max_size
                result["reason"] = f"Size reduced from {size} to {max_size} (max limit)"
        except (TypeError, ValueError) as e:
            logger.warning("Order manager: could not read max_position_size (rejecting order): %s", e)
            result["valid"] = False
            result["reason"] = "Configuration error: max position size invalid"
            return result

        # Check account-based limits if provided
        if account_value is not None and account_value > 0:
            try:
                max_pct = float(self._risk_settings.get("max_position_pct", 0.1) or 0.1)
                estimated_margin = size * _DEFAULT_MARGIN_PER_CONTRACT
                position_pct = estimated_margin / account_value

                if position_pct > max_pct:
                    adjusted = int(account_value * max_pct / _DEFAULT_MARGIN_PER_CONTRACT)
                    adjusted = max(1, adjusted)
                    if adjusted < result["adjusted_size"]:
                        result["adjusted_size"] = adjusted
                        result["reason"] = f"Size reduced to {adjusted} (max {max_pct:.0%} of account)"
            except (TypeError, ValueError) as e:
                logger.debug("Order manager: could not apply account-based limit: %s", e)

        return result

    def get_sizing_summary(self) -> Dict[str, Any]:
        """Return a summary of current sizing configuration."""
        cfg = self._strategy_settings or {}
        return {
            "enable_dynamic_sizing": bool(cfg.get("enable_dynamic_sizing", False)),
            "base_contracts": int(cfg.get("base_contracts", 1) or 1),
            "high_conf_contracts": int(cfg.get("high_conf_contracts", 1) or 1),
            "max_conf_contracts": int(cfg.get("max_conf_contracts", 1) or 1),
            "high_conf_threshold": float(cfg.get("high_conf_threshold", 0.8) or 0.8),
            "max_conf_threshold": float(cfg.get("max_conf_threshold", 0.9) or 0.9),
            "min_position_size": int(self._risk_settings.get("min_position_size", 1) or 1),
            "max_position_size": self._risk_settings.get("max_position_size"),
        }
