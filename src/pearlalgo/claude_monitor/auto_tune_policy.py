"""
Auto-Tune Policy - Bounded safety policy for autonomous config changes.

Enforces:
- Allowlist of config paths that can be auto-modified
- Max step size per config key (prevents drastic changes)
- Live gating (checks execution mode, connection health, error spikes)
- Rate limits (per day + cooldown per key)
- Rollback triggers (automatic rollback + kill/disarm when safety thresholds trip)

This is the "authority" layer - LLM suggestions are just proposals,
the policy decides what actually gets executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_utc_timestamp


# =============================================================================
# ALLOWLIST: Config paths that can be auto-modified
# =============================================================================
# Conservative default: only tune signal/strategy parameters, not execution or risk limits

DEFAULT_ALLOWLIST: Dict[str, Dict[str, Any]] = {
    # Signal generation tuning
    "signals.min_confidence": {
        "type": "float",
        "min": 0.40,
        "max": 0.90,
        "max_delta": 0.10,  # Max change per application
        "description": "Signal confidence threshold",
    },
    "signals.min_risk_reward": {
        "type": "float",
        "min": 1.0,
        "max": 3.0,
        "max_delta": 0.3,
        "description": "Minimum risk/reward ratio",
    },
    "signals.volatility_threshold": {
        "type": "float",
        "min": 0.0001,
        "max": 0.002,
        "max_delta": 0.0005,
        "description": "Volatility gate threshold",
    },
    "signals.duplicate_window_seconds": {
        "type": "int",
        "min": 60,
        "max": 900,
        "max_delta": 120,
        "description": "Duplicate signal dedup window",
    },
    # Strategy tuning
    "strategy.enabled_signals": {
        "type": "list",
        "allowed_values": [
            "sr_bounce", "mean_reversion_long", "mean_reversion_short",
            "momentum_short", "breakout_long", "breakout_short", "vwap_reversion",
        ],
        "description": "Enabled signal types",
    },
    "strategy.disabled_signals": {
        "type": "list",
        "allowed_values": [
            "momentum_long", "engulfing_short", "engulfing_long",
            "sr_bounce", "mean_reversion_long", "mean_reversion_short",
            "momentum_short", "breakout_long", "breakout_short", "vwap_reversion",
        ],
        "description": "Disabled signal types",
    },
    "strategy.base_contracts": {
        "type": "int",
        "min": 1,
        "max": 25,
        "max_delta": 5,
        "description": "Base position size",
    },
    "strategy.high_conf_threshold": {
        "type": "float",
        "min": 0.60,
        "max": 0.95,
        "max_delta": 0.10,
        "description": "High confidence threshold",
    },
    # Risk tuning (conservative)
    "risk.stop_loss_atr_multiplier": {
        "type": "float",
        "min": 1.0,
        "max": 3.0,
        "max_delta": 0.3,
        "description": "Stop loss ATR multiplier",
    },
    "risk.take_profit_risk_reward": {
        "type": "float",
        "min": 1.0,
        "max": 3.0,
        "max_delta": 0.3,
        "description": "Take profit R:R target",
    },
}

# Config paths that are NEVER auto-modifiable (hard blocklist)
BLOCKLIST: Set[str] = {
    # Execution control (manual only)
    "execution.enabled",
    "execution.armed",
    "execution.mode",
    "execution.max_positions",
    "execution.max_orders_per_day",
    "execution.max_daily_loss",
    # Risk hard limits
    "risk.max_risk_per_trade",
    "risk.max_drawdown",
    "risk.max_position_size",
    # Telegram credentials
    "telegram.bot_token",
    "telegram.chat_id",
    # Claude monitor self-modification
    "claude_monitor.auto_apply_enabled",
    "claude_monitor.max_auto_changes_per_day",
}


@dataclass
class PolicyDecision:
    """Result of a policy check."""
    allowed: bool
    reason: str
    config_path: Optional[str] = None
    proposed_value: Optional[Any] = None
    bounded_value: Optional[Any] = None  # Value after bounding
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "config_path": self.config_path,
            "proposed_value": self.proposed_value,
            "bounded_value": self.bounded_value,
            "warnings": self.warnings,
        }


@dataclass
class PolicyConfig:
    """Configuration for the auto-tune policy."""
    # Rate limits
    max_changes_per_day: int = 3
    cooldown_per_key_seconds: int = 3600  # 1 hour between changes to same key
    
    # Live gating
    require_connection_healthy: bool = True
    max_consecutive_errors: int = 5
    block_when_armed: bool = False  # If True, never auto-apply when execution is armed
    
    # Rollback triggers
    error_spike_threshold: int = 10  # Trigger rollback if errors spike
    enable_auto_rollback: bool = True
    create_disarm_flag_on_error: bool = True
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "PolicyConfig":
        return cls(
            max_changes_per_day=int(config.get("max_auto_changes_per_day", 3)),
            cooldown_per_key_seconds=int(config.get("cooldown_per_key_seconds", 3600)),
            require_connection_healthy=bool(config.get("require_connection_healthy", True)),
            max_consecutive_errors=int(config.get("max_consecutive_errors", 5)),
            block_when_armed=bool(config.get("block_when_armed", False)),
            error_spike_threshold=int(config.get("error_spike_threshold", 10)),
            enable_auto_rollback=bool(config.get("enable_auto_rollback", True)),
            create_disarm_flag_on_error=bool(config.get("create_disarm_flag_on_error", True)),
        )


class AutoTunePolicy:
    """
    Safety policy for autonomous config modifications.
    
    Ensures all auto-applied changes are:
    - Within allowlisted config paths
    - Bounded by max delta limits
    - Rate-limited
    - Only applied when system is healthy
    """
    
    def __init__(
        self,
        config: Optional[PolicyConfig] = None,
        state_dir: Optional[Path] = None,
        allowlist: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self.config = config or PolicyConfig()
        self.state_dir = ensure_state_dir(state_dir)
        self.allowlist = allowlist or DEFAULT_ALLOWLIST
        
        # State tracking
        self._policy_state_file = self.state_dir / "auto_tune_policy_state.json"
        self._changes_today: List[Dict[str, Any]] = []
        self._last_change_per_key: Dict[str, datetime] = {}
        self._load_state()
        
        logger.info(
            f"AutoTunePolicy initialized: max_changes_per_day={self.config.max_changes_per_day}, "
            f"allowlist_keys={len(self.allowlist)}"
        )
    
    def _load_state(self) -> None:
        """Load policy state from disk."""
        try:
            if self._policy_state_file.exists():
                with open(self._policy_state_file) as f:
                    state = json.load(f)
                
                # Load today's changes
                today = datetime.now(timezone.utc).date().isoformat()
                if state.get("date") == today:
                    self._changes_today = state.get("changes_today", [])
                else:
                    # New day, reset counter
                    self._changes_today = []
                
                # Load cooldown state
                for key, ts_str in state.get("last_change_per_key", {}).items():
                    try:
                        self._last_change_per_key[key] = datetime.fromisoformat(ts_str)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not load policy state: {e}")
    
    def _save_state(self) -> None:
        """Save policy state to disk."""
        try:
            state = {
                "date": datetime.now(timezone.utc).date().isoformat(),
                "changes_today": self._changes_today,
                "last_change_per_key": {
                    k: v.isoformat() for k, v in self._last_change_per_key.items()
                },
                "last_updated": get_utc_timestamp(),
            }
            with open(self._policy_state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save policy state: {e}")
    
    def check_change(
        self,
        config_path: str,
        old_value: Any,
        new_value: Any,
        agent_state: Optional[Dict[str, Any]] = None,
    ) -> PolicyDecision:
        """
        Check if a proposed config change is allowed.
        
        Args:
            config_path: Dot-separated config path (e.g., "signals.min_confidence")
            old_value: Current config value
            new_value: Proposed new value
            agent_state: Current agent state from state.json (for live gating)
            
        Returns:
            PolicyDecision with allowed status and bounded value
        """
        warnings = []
        
        # Check blocklist
        if config_path in BLOCKLIST:
            return PolicyDecision(
                allowed=False,
                reason=f"Config path '{config_path}' is in blocklist (manual-only)",
                config_path=config_path,
                proposed_value=new_value,
            )
        
        # Check allowlist
        if config_path not in self.allowlist:
            return PolicyDecision(
                allowed=False,
                reason=f"Config path '{config_path}' is not in allowlist",
                config_path=config_path,
                proposed_value=new_value,
            )
        
        spec = self.allowlist[config_path]
        
        # Validate and bound the value
        bounded_value, bound_warnings = self._bound_value(
            config_path, old_value, new_value, spec
        )
        warnings.extend(bound_warnings)
        
        if bounded_value is None:
            return PolicyDecision(
                allowed=False,
                reason=f"Value validation failed for '{config_path}'",
                config_path=config_path,
                proposed_value=new_value,
                warnings=warnings,
            )
        
        # Check rate limits
        rate_allowed, rate_reason = self._check_rate_limits(config_path)
        if not rate_allowed:
            return PolicyDecision(
                allowed=False,
                reason=rate_reason,
                config_path=config_path,
                proposed_value=new_value,
                bounded_value=bounded_value,
                warnings=warnings,
            )
        
        # Check live gating
        if agent_state:
            live_allowed, live_reason = self._check_live_gating(agent_state)
            if not live_allowed:
                return PolicyDecision(
                    allowed=False,
                    reason=live_reason,
                    config_path=config_path,
                    proposed_value=new_value,
                    bounded_value=bounded_value,
                    warnings=warnings,
                )
        
        return PolicyDecision(
            allowed=True,
            reason="Change approved by policy",
            config_path=config_path,
            proposed_value=new_value,
            bounded_value=bounded_value,
            warnings=warnings,
        )
    
    def _bound_value(
        self,
        config_path: str,
        old_value: Any,
        new_value: Any,
        spec: Dict[str, Any],
    ) -> Tuple[Optional[Any], List[str]]:
        """
        Validate and bound a value according to the allowlist spec.
        
        Returns:
            Tuple of (bounded_value, warnings). bounded_value is None if invalid.
        """
        warnings = []
        value_type = spec.get("type", "any")
        
        try:
            if value_type == "float":
                new_val = float(new_value)
                
                # Check min/max
                min_val = spec.get("min")
                max_val = spec.get("max")
                if min_val is not None and new_val < min_val:
                    warnings.append(f"Value {new_val} below min {min_val}, clamping")
                    new_val = min_val
                if max_val is not None and new_val > max_val:
                    warnings.append(f"Value {new_val} above max {max_val}, clamping")
                    new_val = max_val
                
                # Check max delta
                max_delta = spec.get("max_delta")
                if max_delta is not None and old_value is not None:
                    old_val = float(old_value)
                    delta = abs(new_val - old_val)
                    if delta > max_delta:
                        # Clamp to max delta
                        direction = 1 if new_val > old_val else -1
                        new_val = old_val + (direction * max_delta)
                        warnings.append(
                            f"Delta {delta:.4f} exceeds max {max_delta}, bounded to {new_val:.4f}"
                        )
                
                return new_val, warnings
            
            elif value_type == "int":
                new_val = int(float(new_value))  # Handle float -> int
                
                # Check min/max
                min_val = spec.get("min")
                max_val = spec.get("max")
                if min_val is not None and new_val < min_val:
                    warnings.append(f"Value {new_val} below min {min_val}, clamping")
                    new_val = min_val
                if max_val is not None and new_val > max_val:
                    warnings.append(f"Value {new_val} above max {max_val}, clamping")
                    new_val = max_val
                
                # Check max delta
                max_delta = spec.get("max_delta")
                if max_delta is not None and old_value is not None:
                    old_val = int(old_value)
                    delta = abs(new_val - old_val)
                    if delta > max_delta:
                        direction = 1 if new_val > old_val else -1
                        new_val = old_val + (direction * int(max_delta))
                        warnings.append(
                            f"Delta {delta} exceeds max {max_delta}, bounded to {new_val}"
                        )
                
                return new_val, warnings
            
            elif value_type == "list":
                if not isinstance(new_value, list):
                    new_value = [new_value] if new_value else []
                
                allowed_values = set(spec.get("allowed_values", []))
                if allowed_values:
                    # Filter to only allowed values
                    filtered = [v for v in new_value if v in allowed_values]
                    if len(filtered) != len(new_value):
                        removed = set(new_value) - set(filtered)
                        warnings.append(f"Removed invalid values: {removed}")
                    new_value = filtered
                
                return new_value, warnings
            
            elif value_type == "bool":
                return bool(new_value), warnings
            
            else:
                # Unknown type, pass through
                return new_value, warnings
                
        except (ValueError, TypeError) as e:
            warnings.append(f"Type conversion error: {e}")
            return None, warnings
    
    def _check_rate_limits(self, config_path: str) -> Tuple[bool, str]:
        """Check rate limits for a config change."""
        now = datetime.now(timezone.utc)
        
        # Check daily limit
        # Reset if new day
        today = now.date()
        self._changes_today = [
            c for c in self._changes_today
            if datetime.fromisoformat(c.get("timestamp", "2000-01-01")).date() == today
        ]
        
        if len(self._changes_today) >= self.config.max_changes_per_day:
            return False, f"Daily limit reached ({self.config.max_changes_per_day} changes/day)"
        
        # Check per-key cooldown
        last_change = self._last_change_per_key.get(config_path)
        if last_change:
            elapsed = (now - last_change).total_seconds()
            if elapsed < self.config.cooldown_per_key_seconds:
                remaining = int(self.config.cooldown_per_key_seconds - elapsed)
                return False, f"Cooldown active for '{config_path}' ({remaining}s remaining)"
        
        return True, "Rate limits OK"
    
    def _check_live_gating(self, agent_state: Dict[str, Any]) -> Tuple[bool, str]:
        """Check live gating conditions from agent state."""
        execution = agent_state.get("execution", {})

        # Block auto-tuning when execution mode is live (real money at stake)
        # Allow when dry_run or paper mode
        exec_mode = str(execution.get("mode", "")).lower()
        if exec_mode == "live":
            return False, "Auto-tuning blocked while execution mode is live (switch to dry_run first)"

        # Check if execution is armed (optional additional check via config)
        if self.config.block_when_armed and execution.get("armed", False):
            return False, "Auto-apply blocked while execution is armed"
        
        # Check connection health
        if self.config.require_connection_healthy:
            connection_failures = agent_state.get("connection_failures", 0)
            if connection_failures > 3:
                return False, f"Connection unhealthy ({connection_failures} failures)"
        
        # Check error count
        consecutive_errors = agent_state.get("consecutive_errors", 0)
        if consecutive_errors >= self.config.max_consecutive_errors:
            return False, f"Too many consecutive errors ({consecutive_errors})"
        
        # Check if service is running
        if not agent_state.get("running", True):
            return False, "Agent service is not running"
        
        return True, "Live gating OK"
    
    def record_change(
        self,
        config_path: str,
        old_value: Any,
        new_value: Any,
        request_id: str,
    ) -> None:
        """Record a successful config change for rate limiting."""
        now = datetime.now(timezone.utc)
        
        self._changes_today.append({
            "config_path": config_path,
            "old_value": old_value,
            "new_value": new_value,
            "request_id": request_id,
            "timestamp": now.isoformat(),
        })
        
        self._last_change_per_key[config_path] = now
        self._save_state()
        
        logger.info(
            f"Policy recorded change: {config_path} = {new_value} (request_id={request_id})"
        )
    
    def check_rollback_triggers(
        self,
        agent_state: Dict[str, Any],
        previous_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Check if rollback triggers have been tripped.
        
        Args:
            agent_state: Current agent state
            previous_state: State before the last change (if available)
            
        Returns:
            Reason for rollback trigger, or None if no trigger
        """
        if not self.config.enable_auto_rollback:
            return None
        
        # Check for error spike
        current_errors = agent_state.get("consecutive_errors", 0)
        if current_errors >= self.config.error_spike_threshold:
            return f"Error spike detected ({current_errors} consecutive errors)"
        
        # Check for connection loss
        if agent_state.get("connection_failures", 0) >= 5:
            return "Connection failures spike"
        
        # Compare with previous state if available
        if previous_state:
            prev_errors = previous_state.get("consecutive_errors", 0)
            if current_errors - prev_errors >= 3:
                return f"Error count increased significantly ({prev_errors} -> {current_errors})"
        
        return None
    
    def create_safety_flag(self, flag_type: str = "disarm") -> bool:
        """
        Create a safety flag file to trigger agent disarm/kill.
        
        Args:
            flag_type: "disarm" or "kill"
            
        Returns:
            True if flag was created
        """
        if not self.config.create_disarm_flag_on_error:
            return False
        
        try:
            flag_file = self.state_dir / f"{flag_type}_request.flag"
            content = f"{flag_type}_requested_at={get_utc_timestamp()}\nauto_tune_policy_triggered=true"
            flag_file.write_text(content)
            logger.warning(f"Created safety flag: {flag_file}")
            return True
        except Exception as e:
            logger.error(f"Could not create safety flag: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get current policy status."""
        today = datetime.now(timezone.utc).date()
        changes_today = [
            c for c in self._changes_today
            if datetime.fromisoformat(c.get("timestamp", "2000-01-01")).date() == today
        ]
        
        return {
            "changes_today": len(changes_today),
            "max_per_day": self.config.max_changes_per_day,
            "remaining_today": self.config.max_changes_per_day - len(changes_today),
            "allowlist_keys": list(self.allowlist.keys()),
            "block_when_armed": self.config.block_when_armed,
            "auto_rollback_enabled": self.config.enable_auto_rollback,
        }


