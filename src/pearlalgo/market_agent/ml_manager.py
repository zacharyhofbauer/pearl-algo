"""
ML Manager -- encapsulates ML/learning state and logic.

Extracted from MarketAgentService (WS8) to reduce god-object complexity.
Handles:
  - ML signal filter (shadow / live mode)
  - Bandit policy (adaptive signal type selection)
  - Contextual bandit policy (session/regime learning)
  - ML sizing / priority adjustments
  - Lift evaluation (shadow A/B metrics)
  - Shadow tracker (suggestion outcome tracking)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports (mirrors service.py pattern -- keeps ML deps truly optional)
# ---------------------------------------------------------------------------

# Learning layer (bandit policy)
try:
    from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig, BanditDecision
    LEARNING_AVAILABLE = True
except ImportError:
    LEARNING_AVAILABLE = False
    BanditPolicy = None  # type: ignore
    BanditConfig = None  # type: ignore
    BanditDecision = None  # type: ignore

# SQLite trade database
try:
    from pearlalgo.learning.trade_database import TradeDatabase
    TRADE_DB_AVAILABLE = True
except ImportError:
    TRADE_DB_AVAILABLE = False
    TradeDatabase = None  # type: ignore

# Contextual learning (richer session/regime analytics)
try:
    from pearlalgo.learning.contextual_bandit import (
        ContextualBanditPolicy,
        ContextualBanditConfig,
        ContextFeatures,
        ContextualDecision,
    )
    CONTEXTUAL_BANDIT_AVAILABLE = True
except ImportError:
    CONTEXTUAL_BANDIT_AVAILABLE = False
    ContextualBanditPolicy = None  # type: ignore
    ContextualBanditConfig = None  # type: ignore
    ContextFeatures = None  # type: ignore
    ContextualDecision = None  # type: ignore

# ML signal filter (shadow measurement / lift evaluation)
try:
    from pearlalgo.learning.ml_signal_filter import get_ml_signal_filter, MLSignalFilter
    ML_FILTER_AVAILABLE = True
except ImportError:
    ML_FILTER_AVAILABLE = False
    get_ml_signal_filter = None  # type: ignore
    MLSignalFilter = None  # type: ignore

# Shadow tracker removed (restructure Phase 2D)
SHADOW_TRACKER_AVAILABLE = False
get_shadow_tracker = None  # type: ignore
SuggestionType = None  # type: ignore


class MLManager:
    """Manages ML signal filtering, bandit policies, lift evaluation, and shadow tracking.

    Extracted from MarketAgentService to reduce god-object complexity.
    All attributes are directly accessible so that existing delegation via
    ``self._ml_manager.signal_filter`` etc. is concise.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        *,
        service_config: Dict[str, Any],
        state_dir: Path,
        trade_db: Optional[Any] = None,
        sqlite_enabled: bool = False,
        signals_file_path: Optional[Path] = None,
    ) -> None:
        self._state_dir = state_dir
        self._trade_db = trade_db
        self._sqlite_enabled = sqlite_enabled
        self._signals_file_path = signals_file_path

        # Stop-loss ATR multiplier (used to derive ATR from stop distance).
        try:
            self._stop_loss_atr_mult: float = float(
                service_config.get("stop_loss_atr_mult", 3.5) or 3.5
            )
            if self._stop_loss_atr_mult <= 0:
                self._stop_loss_atr_mult = 3.5
        except Exception:
            self._stop_loss_atr_mult = 3.5

        # ===== ML Filter Config =====
        ml_cfg = service_config.get("ml_filter", {}) or {}

        self.filter_mode: str = str(ml_cfg.get("mode", "shadow") or "shadow").lower()
        if self.filter_mode not in ("shadow", "live"):
            self.filter_mode = "shadow"

        self.require_lift_to_block: bool = bool(
            ml_cfg.get("require_lift_to_block", True)
        )
        self.lift_lookback_trades: int = int(
            ml_cfg.get("lift_lookback_trades", 200) or 200
        )
        self.lift_min_trades: int = int(ml_cfg.get("lift_min_trades", 50) or 50)
        self.lift_min_winrate_delta: float = float(
            ml_cfg.get("lift_min_winrate_delta", 0.05) or 0.05
        )

        # Shadow-only threshold for lift measurement.
        self.shadow_threshold: Optional[float] = None
        try:
            st = ml_cfg.get("shadow_threshold", None)
            if st is not None:
                self.shadow_threshold = float(st)
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            self.shadow_threshold = None

        # Default safe: do NOT allow live blocking until we have evaluated lift.
        self.blocking_allowed: bool = False
        self.lift_metrics: Dict[str, Any] = {}
        self.lift_last_eval_at: Optional[datetime] = None

        # ===== ML Sizing Config =====
        self.adjust_sizing: bool = bool(ml_cfg.get("adjust_sizing", False))
        try:
            self.size_multiplier_min: float = float(
                ml_cfg.get("size_multiplier_min", 1.0) or 1.0
            )
            self.size_multiplier_max: float = float(
                ml_cfg.get("size_multiplier_max", 1.5) or 1.5
            )
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            self.size_multiplier_min = 1.0
            self.size_multiplier_max = 1.5
        try:
            self.size_threshold: float = float(
                ml_cfg.get("high_probability", 0.7) or 0.7
            )
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            self.size_threshold = 0.7

        # ===== ML Signal Filter =====
        self.filter_enabled: bool = bool(ml_cfg.get("enabled", False))
        self.signal_filter: Optional[Any] = None
        self.filter_init_status: Dict[str, Any] = {}
        self._init_signal_filter(ml_cfg, service_config)

        # ===== Bandit / Contextual Policy =====
        self.bandit_policy: Optional[Any] = None
        self.bandit_config: Optional[Any] = None
        self.contextual_policy: Optional[Any] = None
        self.contextual_config: Optional[Any] = None
        self._init_learning(service_config, state_dir)

        # ===== Shadow Tracker =====
        self.shadow_tracker: Optional[Any] = None
        self._init_shadow_tracker(state_dir)

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _init_signal_filter(
        self, ml_cfg: Dict[str, Any], service_config: Dict[str, Any]
    ) -> None:
        """Initialize ML signal filter (shadow / live mode)."""
        if not self.filter_enabled:
            return

        if not ML_FILTER_AVAILABLE or get_ml_signal_filter is None:
            logger.warning(
                "ML filter enabled in config, but dependencies unavailable (skipping)"
            )
            self.filter_enabled = False
            return

        try:
            train_limit = int(ml_cfg.get("training_max_samples", 2000) or 2000)
            trades_for_training = self.build_training_trades_from_signals(
                limit=train_limit
            )
            self.signal_filter = get_ml_signal_filter(
                config=service_config, trades=trades_for_training
            )
            self.filter_init_status = {
                "enabled": True,
                "mode": str(self.filter_mode),
                "trained": bool(getattr(self.signal_filter, "is_ready", False)),
                "training_samples": int(len(trades_for_training)),
            }
            logger.info(
                "ML filter initialized",
                extra={
                    "mode": self.filter_mode,
                    "trained": bool(
                        getattr(self.signal_filter, "is_ready", False)
                    ),
                    "training_samples": int(len(trades_for_training)),
                },
            )
        except Exception as e:
            logger.warning("ML filter init failed (continuing without): %s", e)
            self.signal_filter = None
            self.filter_enabled = False

    def _init_learning(
        self, service_config: Dict[str, Any], state_dir: Path
    ) -> None:
        """Initialize bandit and contextual bandit policies."""
        learning_settings = service_config.get("learning", {})

        # -- Bandit policy --
        if LEARNING_AVAILABLE and learning_settings.get("enabled", True):
            try:
                self.bandit_config = BanditConfig.from_dict(learning_settings)
                self.bandit_policy = BanditPolicy(
                    config=self.bandit_config,
                    state_dir=state_dir,
                )
                logger.info(
                    "Bandit policy initialized: mode=%s, threshold=%s, explore_rate=%s",
                    self.bandit_config.mode,
                    self.bandit_config.decision_threshold,
                    self.bandit_config.explore_rate,
                )
            except Exception as e:
                logger.error(
                    "Failed to initialize bandit policy: %s", e, exc_info=True
                )
                self.bandit_policy = None
        else:
            if not LEARNING_AVAILABLE:
                logger.debug("Learning layer not available (import failed)")
            else:
                logger.info("Bandit policy disabled (learning.enabled=false)")

        # -- Contextual bandit policy --
        if CONTEXTUAL_BANDIT_AVAILABLE:
            contextual_settings = learning_settings.get("contextual", {})
            if not isinstance(contextual_settings, dict):
                contextual_settings = {}
            if bool(contextual_settings.get("enabled", False)):
                try:
                    self.contextual_config = ContextualBanditConfig.from_dict(
                        contextual_settings
                    )
                    self.contextual_policy = ContextualBanditPolicy(
                        config=self.contextual_config,
                        state_dir=state_dir,
                    )
                    logger.info(
                        "Contextual policy initialized: mode=%s threshold=%s explore_rate=%s",
                        getattr(self.contextual_config, "mode", "shadow"),
                        getattr(
                            self.contextual_config, "decision_threshold", 0.3
                        ),
                        getattr(self.contextual_config, "explore_rate", 0.1),
                    )
                except Exception as e:
                    logger.error(
                        "Failed to initialize contextual bandit policy: %s",
                        e,
                        exc_info=True,
                    )
                    self.contextual_policy = None
            else:
                logger.info(
                    "Contextual policy disabled (learning.contextual.enabled=false)"
                )
        else:
            logger.debug("Contextual bandit not available (import failed)")

    def _init_shadow_tracker(self, state_dir: Path) -> None:
        """Initialize Pearl AI shadow tracker (tracks suggestion outcomes)."""
        if SHADOW_TRACKER_AVAILABLE and get_shadow_tracker is not None:
            try:
                self.shadow_tracker = get_shadow_tracker(state_dir=state_dir)
            except Exception as e:
                logger.warning(
                    "Shadow tracker init failed (continuing without): %s", e
                )
                self.shadow_tracker = None
        else:
            logger.debug("Shadow tracker not available (import failed)")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ml_enabled(self) -> bool:
        """True if ML signal filter is enabled and initialized."""
        return self.filter_enabled and self.signal_filter is not None

    @property
    def is_learning_enabled(self) -> bool:
        """True if any learning policy (bandit or contextual) is active."""
        return (
            self.bandit_policy is not None
            or self.contextual_policy is not None
        )

    @property
    def is_filter_trained(self) -> bool:
        """True if ML signal filter is trained and ready for predictions."""
        if self.signal_filter is None:
            return False
        return bool(getattr(self.signal_filter, "is_ready", False))

    # ------------------------------------------------------------------
    # ML Lift Evaluation
    # ------------------------------------------------------------------

    def compute_lift_metrics(self, trades: list) -> Dict[str, Any]:
        """Compute shadow A/B lift for ML gating.

        Compare outcomes for trades where ML would PASS vs would BLOCK.
        Expects trade dicts from TradeDatabase.get_recent_trades_by_exit().
        """
        if not isinstance(trades, list) or not trades:
            return {
                "status": "no_trades",
                "lift_ok": False,
                "blocking_allowed": False,
            }

        # Filter to trades with real ML predictions (exclude fallback-only).
        scored: List[dict] = []
        for t in trades:
            if not isinstance(t, dict):
                continue
            feats = t.get("features", {})
            if not isinstance(feats, dict):
                continue
            has_prob = (
                "ml_win_probability" in feats
                and feats.get("ml_win_probability") is not None
            )
            has_flag = "ml_pass_filter" in feats
            if not (has_prob or has_flag):
                continue
            try:
                if float(feats.get("ml_fallback_used", 0.0) or 0.0) >= 0.5:
                    continue
            except Exception as e:
                logger.debug("Non-critical: %s", e)
            scored.append(t)

        total_scored = len(scored)

        # Determine pass/fail groups using probability-based thresholding.
        pass_group: List[dict] = []
        fail_group: List[dict] = []
        threshold_used: Optional[float] = None

        for t in scored:
            feats = t.get("features", {}) or {}

            thr: Optional[float] = None
            try:
                if feats.get("ml_pass_threshold") is not None:
                    thr = float(feats.get("ml_pass_threshold") or 0.0)
            except Exception as e:
                logger.debug("Non-critical: %s", e)
                thr = None
            if thr is None:
                try:
                    if (
                        self.filter_mode == "shadow"
                        and self.shadow_threshold is not None
                    ):
                        thr = float(self.shadow_threshold)
                except Exception as e:
                    logger.debug("Non-critical: %s", e)
                    thr = None

            pass_flag = True
            if thr is not None:
                threshold_used = float(thr)
                try:
                    p = float(feats.get("ml_win_probability", 0.0) or 0.0)
                    pass_flag = p >= float(thr)
                except Exception as e:
                    logger.debug("Non-critical: %s", e)
                    pass_flag = True
            else:
                try:
                    pass_flag = (
                        float(feats.get("ml_pass_filter", 1.0) or 0.0) >= 0.5
                    )
                except Exception as e:
                    logger.debug("Non-critical: %s", e)
                    pass_flag = True

            if pass_flag:
                pass_group.append(t)
            else:
                fail_group.append(t)

        if total_scored < self.lift_min_trades:
            out: Dict[str, Any] = {
                "status": "insufficient_data",
                "scored_trades": total_scored,
                "min_trades": self.lift_min_trades,
                "pass_trades": int(len(pass_group)),
                "fail_trades": int(len(fail_group)),
                "lift_ok": False,
                "blocking_allowed": False,
            }
            if threshold_used is not None:
                out["pass_threshold_used"] = float(threshold_used)
            return out

        if not pass_group or not fail_group:
            out = {
                "status": "no_split",
                "scored_trades": total_scored,
                "pass_trades": len(pass_group),
                "fail_trades": len(fail_group),
                "lift_ok": False,
                "blocking_allowed": False,
                "reason": "Need both pass+fail groups to measure lift",
            }
            if threshold_used is not None:
                out["pass_threshold_used"] = float(threshold_used)
            return out

        def _wr(xs: list) -> float:
            wins = 0
            for t_inner in xs:
                try:
                    if bool(t_inner.get("is_win", False)):
                        wins += 1
                except Exception as e:
                    logger.debug("Non-critical: %s", e)
                    continue
            return wins / max(1, len(xs))

        def _avg_pnl(xs: list) -> float:
            vals: List[float] = []
            for t_inner in xs:
                try:
                    vals.append(float(t_inner.get("pnl", 0.0) or 0.0))
                except Exception as e:
                    logger.debug("Non-critical: %s", e)
                    continue
            return float(sum(vals) / max(1, len(vals))) if vals else 0.0

        wr_pass = _wr(pass_group)
        wr_fail = _wr(fail_group)
        lift_wr = wr_pass - wr_fail
        avg_pnl_pass = _avg_pnl(pass_group)
        avg_pnl_fail = _avg_pnl(fail_group)
        lift_pnl = avg_pnl_pass - avg_pnl_fail

        min_delta = self.lift_min_winrate_delta
        lift_ok = bool(lift_wr >= min_delta)

        if self.require_lift_to_block:
            blocking_allowed = bool(self.filter_mode == "live" and lift_ok)
        else:
            blocking_allowed = bool(self.filter_mode == "live")

        return {
            "status": "ok",
            "scored_trades": total_scored,
            "pass_trades": len(pass_group),
            "fail_trades": len(fail_group),
            "win_rate_pass": float(wr_pass),
            "win_rate_fail": float(wr_fail),
            "lift_win_rate": float(lift_wr),
            "avg_pnl_pass": float(avg_pnl_pass),
            "avg_pnl_fail": float(avg_pnl_fail),
            "lift_avg_pnl": float(lift_pnl),
            "lift_ok": bool(lift_ok),
            "lift_min_winrate_delta": float(min_delta),
            "pass_threshold_used": (
                float(threshold_used) if threshold_used is not None else None
            ),
            "mode": self.filter_mode,
            "require_lift_to_block": bool(self.require_lift_to_block),
            "blocking_allowed": bool(blocking_allowed),
        }

    def refresh_lift(self, *, force: bool = False) -> None:
        """Refresh ML lift metrics + blocking allowance (best-effort)."""
        try:
            if not self._sqlite_enabled or self._trade_db is None:
                self.lift_metrics = {
                    "status": "sqlite_disabled",
                    "lift_ok": False,
                    "blocking_allowed": False,
                }
                self.blocking_allowed = False
                return

            now = datetime.now(timezone.utc)
            if (not force) and self.lift_last_eval_at is not None:
                if (now - self.lift_last_eval_at).total_seconds() < 300:
                    return

            trades = self._trade_db.get_recent_trades_by_exit(
                limit=int(self.lift_lookback_trades or 200)
            )
            metrics = self.compute_lift_metrics(trades)
            self.lift_metrics = metrics
            self.blocking_allowed = bool(metrics.get("blocking_allowed", False))
            self.lift_last_eval_at = now
        except Exception as e:
            logger.debug("Could not refresh ML lift metrics: %s", e)

    # ------------------------------------------------------------------
    # Training Data
    # ------------------------------------------------------------------

    def build_training_trades_from_signals(
        self, *, limit: int = 2000
    ) -> list[dict]:
        """Build supervised training samples from signals.jsonl.

        Lightweight: uses only data already persisted with each signal.
        """
        try:
            lim = max(1, int(limit or 2000))
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            lim = 2000

        try:
            path = self._signals_file_path
            if not path:
                return []
            if not Path(path).exists():
                return []
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            return []

        stop_mult = self._stop_loss_atr_mult

        samples: deque[dict] = deque(maxlen=lim)
        try:
            with open(str(path), "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if str(rec.get("status") or "").lower() != "exited":
                        continue

                    # Label
                    if "is_win" in rec:
                        is_win = bool(rec.get("is_win"))
                    else:
                        outcome = str(rec.get("outcome") or "").lower()
                        if outcome not in ("win", "loss"):
                            continue
                        is_win = outcome == "win"

                    sig = rec.get("signal") or {}
                    if not isinstance(sig, dict):
                        sig = {}

                    try:
                        confidence = float(sig.get("confidence") or 0.0)
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        confidence = 0.0
                    try:
                        rr = float(sig.get("risk_reward") or 0.0)
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        rr = 0.0

                    atr_val = 0.0
                    try:
                        entry = float(
                            sig.get("entry_price")
                            or rec.get("entry_price")
                            or 0.0
                        )
                        stop = float(sig.get("stop_loss") or 0.0)
                        if entry > 0 and stop > 0 and stop_mult > 0:
                            atr_val = abs(entry - stop) / stop_mult
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        atr_val = 0.0

                    vol_ratio = 1.0
                    try:
                        mr = sig.get("market_regime") or {}
                        if (
                            isinstance(mr, dict)
                            and mr.get("volatility_ratio") is not None
                        ):
                            vol_ratio = float(
                                mr.get("volatility_ratio") or 1.0
                            )
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        vol_ratio = 1.0

                    regime_dict: Dict[str, Any] = {}
                    try:
                        mr = sig.get("market_regime") or {}
                        if isinstance(mr, dict):
                            regime_type = str(mr.get("regime") or "")
                            regime_dict["regime"] = regime_type
                            vb = "normal"
                            try:
                                if float(vol_ratio) < 0.8:
                                    vb = "low"
                                elif float(vol_ratio) > 1.5:
                                    vb = "high"
                            except Exception as e:
                                logger.debug("Non-critical: %s", e)
                                vb = "normal"
                            regime_dict["volatility"] = vb
                            regime_dict["session"] = str(
                                mr.get("session") or ""
                            )
                    except Exception as e:
                        logger.debug("Non-critical: %s", e)
                        regime_dict = {}

                    sample = {
                        "signal_type": str(
                            rec.get("signal_type")
                            or sig.get("type")
                            or "unknown"
                        ),
                        "is_win": bool(is_win),
                        "exit_time": str(
                            rec.get("exit_time")
                            or rec.get("timestamp")
                            or ""
                        ),
                        "confidence": float(confidence),
                        "risk_reward": float(rr),
                        "atr": float(atr_val),
                        "volatility_ratio": float(vol_ratio),
                        "volume_ratio": 1.0,
                        "rsi": 0.0,
                        "macd_histogram": 0.0,
                        "bb_position": 0.0,
                        "vwap_distance": 0.0,
                    }
                    if regime_dict:
                        sample["regime"] = regime_dict

                    samples.append(sample)
        except Exception as e:
            logger.debug("Non-critical: %s", e)
            return []

        return list(samples)

    async def build_training_trades_from_signals_async(
        self, *, limit: int = 2000
    ) -> list[dict]:
        """Async wrapper -- runs file I/O in a thread."""
        return await asyncio.to_thread(
            self.build_training_trades_from_signals, limit=limit
        )

    # ------------------------------------------------------------------
    # ML Sizing
    # ------------------------------------------------------------------

    def apply_opportunity_sizing(
        self,
        signal: Dict,
        *,
        base_size: int,
        risk_settings: Dict[str, Any],
    ) -> None:
        """Adjust size and priority based on ML opportunity signal.

        Args:
            signal: Mutable signal dict (modified in-place).
            base_size: Pre-computed base position size from the service.
            risk_settings: Risk settings dict (for min/max position clamping).
        """
        if not self.adjust_sizing:
            return

        pred = signal.get("_ml_prediction") or {}
        try:
            win_prob = float(pred.get("win_probability"))
        except Exception as e:
            logger.warning(
                "Failed to parse ML win probability for sizing: %s", e
            )
            return

        multiplier = (
            self.size_multiplier_max
            if win_prob >= self.size_threshold
            else self.size_multiplier_min
        )
        try:
            adjusted = int(round(base_size * float(multiplier)))
        except Exception as e:
            logger.warning("Failed to apply ML size multiplier: %s", e)
            adjusted = base_size

        try:
            min_size = int(risk_settings.get("min_position_size", 1) or 1)
        except Exception as e:
            logger.warning(
                "Failed to parse min position size for ML sizing: %s", e
            )
            min_size = 1
        try:
            max_size = int(
                risk_settings.get("max_position_size", adjusted) or adjusted
            )
        except Exception as e:
            logger.warning(
                "Failed to parse max position size for ML sizing: %s", e
            )
            max_size = adjusted

        adjusted = max(min_size, min(max_size, adjusted))
        adjusted = max(1, adjusted)

        signal["position_size"] = adjusted
        signal["_ml_size_multiplier"] = float(multiplier)
        signal["_ml_size_adjusted"] = True

        if win_prob >= self.size_threshold:
            signal["_ml_priority"] = "critical"
        else:
            signal["_ml_priority"] = "high"

        if adjusted != base_size:
            logger.info(
                "ML sizing adjusted position size: %d -> %d (p=%.2f, mult=%.2f)",
                base_size,
                adjusted,
                win_prob,
                multiplier,
            )

    # ------------------------------------------------------------------
    # Status Snapshots
    # ------------------------------------------------------------------

    def get_filter_status(self) -> Dict[str, Any]:
        """Return ML filter operational status dict (for /status)."""
        return {
            "enabled": bool(self.filter_enabled),
            "mode": self.filter_mode,
            "trained": self.is_filter_trained,
            "require_lift_to_block": bool(self.require_lift_to_block),
            "blocking_allowed": bool(self.blocking_allowed),
            "lift": self.lift_metrics or {},
            "last_eval_at": (
                self.lift_last_eval_at.isoformat()
                if self.lift_last_eval_at is not None
                else None
            ),
        }

    def get_learning_status(self) -> Dict[str, Any]:
        """Return bandit policy status dict (for /status)."""
        if self.bandit_policy is not None:
            return self.bandit_policy.get_status()
        return {"enabled": False, "mode": "disabled"}

    def get_contextual_status(self) -> Dict[str, Any]:
        """Return contextual policy status dict (for /status)."""
        if self.contextual_policy is not None:
            return self.contextual_policy.get_status()
        return {"enabled": False, "mode": "disabled"}
