"""
Signal Policy (Centralized Allow/Deny Rules)

This module consolidates signal gating rules so they don't drift across:
- config.yaml (signals.*, strategy.*)
- strategies/nq_intraday/signal_generator.py
- strategies/nq_intraday/scanner.py

It answers a simple question:
  Given a candidate signal + current context, should we allow it to be emitted/executed?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SignalPolicyDecision:
    allowed: bool
    reason: str = ""
    details: Optional[Dict[str, Any]] = None


class SignalPolicy:
    """
    Centralized signal policy based on canonical config:
      - signals.min_confidence
      - signals.min_risk_reward
      - signals.regime_filters[signal_type]
      - strategy.enabled_signals / strategy.disabled_signals (handled earlier in scanner config)

    This policy is intentionally narrow: it should not mutate the signal; it should only decide.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config or {}
        self._signals_cfg = (self._config.get("signals", {}) or {}) if isinstance(self._config, dict) else {}
        self._min_conf = float(self._signals_cfg.get("min_confidence", 0.5) or 0.5)
        self._min_rr = float(self._signals_cfg.get("min_risk_reward", 1.5) or 1.5)
        self._regime_filters = self._signals_cfg.get("regime_filters", {}) or {}

    def evaluate(
        self,
        signal: Dict[str, Any],
        *,
        min_confidence: Optional[float] = None,
        min_risk_reward: Optional[float] = None,
    ) -> SignalPolicyDecision:
        """
        Evaluate a candidate signal against policy.

        Expected minimal signal fields:
          - type
          - confidence
          - direction
          - entry_price
          - stop_loss
          - take_profit
          - regime (dict with keys: regime/session/volatility) [optional but recommended]
        """
        if not isinstance(signal, dict):
            return SignalPolicyDecision(False, "invalid_signal")

        signal_type = str(signal.get("type") or "unknown")
        # Allow callers to temporarily tighten/relax thresholds without mutating config.
        try:
            eff_min_conf = float(self._min_conf if min_confidence is None else float(min_confidence))
        except Exception:
            eff_min_conf = float(self._min_conf)
        try:
            eff_min_rr = float(self._min_rr if min_risk_reward is None else float(min_risk_reward))
        except Exception:
            eff_min_rr = float(self._min_rr)
        try:
            confidence = float(signal.get("confidence", 0.0) or 0.0)
        except Exception:
            confidence = 0.0

        if confidence < eff_min_conf:
            return SignalPolicyDecision(
                False,
                "confidence",
                {"confidence": confidence, "min_confidence": eff_min_conf},
            )

        # Risk/reward geometry check
        rr = self._compute_rr(signal)
        if rr is not None and rr < eff_min_rr:
            return SignalPolicyDecision(
                False,
                "risk_reward",
                {"risk_reward": rr, "min_risk_reward": eff_min_rr},
            )

        # Regime/session filter (canonical: signals.regime_filters)
        rf = self._regime_filters.get(signal_type)
        if isinstance(rf, dict):
            regime = signal.get("regime", {}) or {}
            regime_type = str(regime.get("regime") or "").strip()
            session = str(regime.get("session") or "").strip()

            allowed_regimes = rf.get("allowed_regimes")
            if allowed_regimes and regime_type:
                if regime_type not in list(allowed_regimes):
                    return SignalPolicyDecision(
                        False,
                        "regime",
                        {"regime": regime_type, "allowed_regimes": list(allowed_regimes)},
                    )

            forbidden_regimes = rf.get("forbidden_regimes") or rf.get("disallowed_regimes")
            if forbidden_regimes and regime_type:
                if regime_type in list(forbidden_regimes):
                    return SignalPolicyDecision(
                        False,
                        "regime_forbidden",
                        {"regime": regime_type, "forbidden_regimes": list(forbidden_regimes)},
                    )

            allowed_sessions = rf.get("allowed_sessions")
            if allowed_sessions and session:
                if session not in list(allowed_sessions):
                    return SignalPolicyDecision(
                        False,
                        "session",
                        {"session": session, "allowed_sessions": list(allowed_sessions)},
                    )

        return SignalPolicyDecision(True, "allowed")

    @staticmethod
    def _compute_rr(signal: Dict[str, Any]) -> Optional[float]:
        try:
            entry = float(signal.get("entry_price", 0.0) or 0.0)
            stop = float(signal.get("stop_loss", 0.0) or 0.0)
            target = float(signal.get("take_profit", 0.0) or 0.0)
            direction = str(signal.get("direction", "long") or "long").lower()
        except Exception:
            return None

        if entry <= 0 or stop <= 0 or target <= 0:
            return None

        if direction == "long":
            risk = entry - stop
            reward = target - entry
        else:
            risk = stop - entry
            reward = entry - target

        if risk <= 0:
            return None
        return float(reward / risk)
