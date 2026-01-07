"""
Drift Guard (Risk Cooldown / "Risk-Off" Safety)

Goal:
- Detect when conditions materially degrade (performance drop or volatility shock)
- Enter a cooldown window that:
  - tightens signal filters (min_confidence / min_risk_reward)
  - reduces position sizing (multiplier)
- Persist state so restarts don't forget the cooldown

This is intentionally conservative and transparent: it emits a small state dict that
is stored in state.json and attached to signals for later analysis.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.utils.logger import logger


def _parse_dt(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


@dataclass
class DriftGuardConfig:
    """Config for drift detection + cooldown behavior."""

    enabled: bool = True

    # Performance trigger (recent outcomes)
    lookback_trades: int = 20
    min_trades: int = 10
    win_rate_floor: float = 0.40  # Trigger when WR over lookback drops below this

    # Volatility trigger (regime shock)
    volatility_spike_enabled: bool = True
    volatility_levels: List[str] = field(default_factory=lambda: ["high", "extreme"])
    require_atr_expansion: bool = True  # Only trigger on high vol when ATR expansion flag is set

    # Cooldown window
    cooldown_minutes: int = 60

    # Adjustments applied during cooldown
    tighten_min_confidence_delta: float = 0.05
    tighten_min_risk_reward_delta: float = 0.20
    size_multiplier: float = 0.50

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "DriftGuardConfig":
        dg = (config.get("drift_guard", {}) or {}) if isinstance(config, dict) else {}
        return cls(
            enabled=bool(dg.get("enabled", True)),
            lookback_trades=int(dg.get("lookback_trades", 20)),
            min_trades=int(dg.get("min_trades", 10)),
            win_rate_floor=float(dg.get("win_rate_floor", 0.40)),
            volatility_spike_enabled=bool(dg.get("volatility_spike_enabled", True)),
            volatility_levels=list(dg.get("volatility_levels", ["high", "extreme"])),
            require_atr_expansion=bool(dg.get("require_atr_expansion", True)),
            cooldown_minutes=int(dg.get("cooldown_minutes", 60)),
            tighten_min_confidence_delta=float(dg.get("tighten_min_confidence_delta", 0.05)),
            tighten_min_risk_reward_delta=float(dg.get("tighten_min_risk_reward_delta", 0.20)),
            size_multiplier=float(dg.get("size_multiplier", 0.50)),
        )


@dataclass
class DriftGuardState:
    """Current drift guard state (persisted)."""

    active: bool = False
    until: Optional[str] = None  # ISO timestamp when cooldown ends (UTC)
    reason: str = ""
    triggered_at: Optional[str] = None
    last_evaluated_at: Optional[str] = None

    # Most recent diagnostics snapshot (for observability)
    sample_trades: int = 0
    win_rate: Optional[float] = None
    volatility: Optional[str] = None
    atr_expansion: Optional[bool] = None

    def is_active(self, now: Optional[datetime] = None) -> bool:
        now_utc = now.astimezone(timezone.utc) if (now and now.tzinfo) else (now or datetime.now(timezone.utc))
        until_dt = _parse_dt(self.until)
        return bool(self.active and until_dt is not None and now_utc < until_dt)

    def adjustments(self, cfg: DriftGuardConfig) -> Dict[str, Any]:
        """Return the current policy adjustments implied by this state."""
        if self.is_active():
            return {
                "min_confidence_delta": float(cfg.tighten_min_confidence_delta),
                "min_risk_reward_delta": float(cfg.tighten_min_risk_reward_delta),
                "size_multiplier": float(cfg.size_multiplier),
            }
        return {
            "min_confidence_delta": 0.0,
            "min_risk_reward_delta": 0.0,
            "size_multiplier": 1.0,
        }

    def to_dict(self, cfg: Optional[DriftGuardConfig] = None) -> Dict[str, Any]:
        d = asdict(self)
        if cfg is not None:
            d["adjustments"] = self.adjustments(cfg)
        return d


class DriftGuard:
    """
    Drift guard engine.

    - Stateless inputs (recent_trades, current regime)
    - Stateful output (cooldown window) persisted to disk
    """

    def __init__(self, config: DriftGuardConfig, state_path: Path):
        self.config = config
        self.state_path = Path(state_path)
        self.state = self._load_state()
        # Ensure a state file exists for operators (/brain) even before the first trigger.
        try:
            self._save_state()
        except Exception:
            pass

    def _load_state(self) -> DriftGuardState:
        try:
            if not self.state_path.exists():
                return DriftGuardState()
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return DriftGuardState()
            return DriftGuardState(
                active=bool(data.get("active", False)),
                until=data.get("until"),
                reason=str(data.get("reason", "") or ""),
                triggered_at=data.get("triggered_at"),
                last_evaluated_at=data.get("last_evaluated_at"),
                sample_trades=int(data.get("sample_trades", 0) or 0),
                win_rate=(float(data.get("win_rate")) if data.get("win_rate") is not None else None),
                volatility=(str(data.get("volatility")) if data.get("volatility") is not None else None),
                atr_expansion=(bool(data.get("atr_expansion")) if data.get("atr_expansion") is not None else None),
            )
        except Exception as e:
            logger.debug(f"Could not load drift guard state: {e}")
            return DriftGuardState()

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self.state.to_dict(self.config)
            self.state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Could not save drift guard state: {e}")

    def update(
        self,
        *,
        regime: Optional[Dict[str, Any]] = None,
        recent_trades: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> Tuple[DriftGuardState, Dict[str, Any]]:
        """
        Update drift guard state.

        Returns:
            (state, transition)
            transition is a small dict like {"triggered": bool, "ended": bool, "reason": "..."}
        """
        now_utc = now.astimezone(timezone.utc) if (now and now.tzinfo) else (now or datetime.now(timezone.utc))

        prev_active = self.state.is_active(now_utc)
        prev_until = _parse_dt(self.state.until)
        prev_reason = str(self.state.reason or "")

        trades = recent_trades or []
        if not isinstance(trades, list):
            trades = []

        # Compute recent WR (last N exits)
        lookback = max(0, int(self.config.lookback_trades))
        sample = trades[:lookback] if lookback > 0 else trades
        wins = 0
        for t in sample:
            try:
                if bool(t.get("is_win", False)):
                    wins += 1
            except Exception:
                continue
        n = len(sample)
        win_rate = (wins / n) if n > 0 else None

        # Regime snapshot
        vol = None
        atr_exp = None
        if isinstance(regime, dict):
            try:
                vol = str(regime.get("volatility", "") or "").lower() or None
            except Exception:
                vol = None
            try:
                atr_exp = bool(regime.get("atr_expansion", False))
            except Exception:
                atr_exp = None

        # Determine triggers
        reasons: List[str] = []
        if self.config.enabled:
            # Performance trigger
            if n >= int(self.config.min_trades) and win_rate is not None:
                if float(win_rate) < float(self.config.win_rate_floor):
                    reasons.append(f"win_rate_drop({win_rate:.0%}<{self.config.win_rate_floor:.0%},n={n})")

            # Volatility shock trigger
            if self.config.volatility_spike_enabled and vol:
                if vol in [str(x).lower() for x in (self.config.volatility_levels or [])]:
                    if (not self.config.require_atr_expansion) or bool(atr_exp):
                        reasons.append(f"vol_spike(vol={vol},atr_exp={bool(atr_exp)})")

        triggered = bool(reasons)

        # Update state machine
        transition: Dict[str, Any] = {"triggered": False, "ended": False, "reason": ""}

        # Start/extend cooldown on trigger
        if triggered:
            new_until = now_utc + timedelta(minutes=int(self.config.cooldown_minutes))
            if prev_until and prev_until > new_until:
                new_until = prev_until  # never shorten an existing cooldown

            new_reason = "; ".join(reasons)[:200]
            entered = not prev_active
            extended = bool(prev_until and new_until > prev_until)
            reason_changed = (new_reason != prev_reason)

            self.state.active = True
            self.state.until = new_until.isoformat()
            self.state.reason = new_reason
            self.state.triggered_at = now_utc.isoformat()
            # Only flag "triggered" on meaningful transitions (enter/extend/reason change),
            # so callers can send alerts without spamming every cycle.
            transition["triggered"] = bool(entered or extended or reason_changed)
            transition["reason"] = self.state.reason
        else:
            # If cooldown expired, end it
            if prev_active and (prev_until is None or now_utc >= prev_until):
                self.state.active = False
                self.state.until = None
                self.state.reason = ""
                transition["ended"] = True

        # Update observability fields
        self.state.last_evaluated_at = now_utc.isoformat()
        self.state.sample_trades = int(n)
        self.state.win_rate = float(win_rate) if win_rate is not None else None
        self.state.volatility = vol
        self.state.atr_expansion = atr_exp

        # Persist if something meaningful changed
        if transition.get("triggered") or transition.get("ended") or (prev_active != self.state.is_active(now_utc)):
            self._save_state()

        return self.state, transition


