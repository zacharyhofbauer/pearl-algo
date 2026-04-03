"""
Helpers for migrating legacy PEARL config shapes to the canonical runtime model.

DEPRECATED: This module exists only to bridge legacy config formats.
Scheduled for removal once all configs use the canonical structure.
New configs should be authored directly in the canonical format
(see config/live/tradovate_paper.yaml as reference).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from pearlalgo.strategies.registry import ACTIVE_STRATEGY
from pearlalgo.utils.logger import logger

_DEPRECATION_LOGGED = False


def migrate_legacy_runtime_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize legacy config shapes into the canonical runtime model.

    This keeps legacy files readable during the transition while making the
    active runtime, API, and strategy loader converge on one structure.

    .. deprecated::
        This function will be removed in a future release. Migrate your
        config files to the canonical format.
    """
    global _DEPRECATION_LOGGED
    migrated = deepcopy(dict(raw or {}))

    strategy_cfg = migrated.get("strategy", {}) or {}
    if not isinstance(strategy_cfg, dict):
        strategy_cfg = {}
    strategy_cfg.setdefault("active", ACTIVE_STRATEGY)
    strategy_cfg.setdefault("enforce_session_window", True)
    migrated["strategy"] = strategy_cfg

    strategies_cfg = migrated.get("strategies", {}) or {}
    if not isinstance(strategies_cfg, dict):
        strategies_cfg = {}

    if ACTIVE_STRATEGY not in strategies_cfg:
        legacy_params = migrated.get("pearl_bot_auto", {}) or {}
        strategies_cfg[ACTIVE_STRATEGY] = deepcopy(legacy_params if isinstance(legacy_params, dict) else {})
        if legacy_params and not _DEPRECATION_LOGGED:
            _DEPRECATION_LOGGED = True
            logger.warning(
                "DEPRECATED: config uses legacy 'pearl_bot_auto' section — "
                "migrate to 'strategies.composite_intraday' in your YAML config. "
                "This compatibility bridge will be removed in a future release."
            )

    migrated["strategies"] = strategies_cfg

    guardrails_cfg = migrated.get("guardrails", {}) or {}
    if not isinstance(guardrails_cfg, dict):
        guardrails_cfg = {}

    legacy_gate_cfg = migrated.get("trading_circuit_breaker", {}) or {}
    if isinstance(legacy_gate_cfg, dict):
        guardrails_cfg.setdefault("signal_gate_enabled", False)
        if "max_consecutive_losses" in legacy_gate_cfg:
            guardrails_cfg.setdefault("max_consecutive_losses", legacy_gate_cfg["max_consecutive_losses"])
        if "max_session_drawdown" in legacy_gate_cfg:
            guardrails_cfg.setdefault("max_session_drawdown", legacy_gate_cfg["max_session_drawdown"])
        if "max_daily_drawdown" in legacy_gate_cfg:
            guardrails_cfg.setdefault("max_daily_drawdown", legacy_gate_cfg["max_daily_drawdown"])

    migrated["guardrails"] = guardrails_cfg
    return migrated
