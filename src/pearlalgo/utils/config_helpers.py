"""
Typed configuration value extraction helpers.

Replaces the pervasive ``try: val = cast(cfg.get(key, default)); except: pass``
pattern with consistent, logged, DRY utilities.

Usage::

    from pearlalgo.utils.config_helpers import safe_get_float, safe_get_int

    threshold = safe_get_float(cfg, "min_confidence", 0.5)
    contracts = safe_get_int(cfg, "base_contracts", 1)

All helpers:
- Return the *default* when the key is missing or the value is ``None``.
- Return the *default* and log a warning when the value cannot be cast.
- Never raise on bad input (safe for production).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def safe_get_float(
    cfg: Dict[str, Any],
    key: str,
    default: float = 0.0,
    *,
    warn: bool = True,
    context: str = "",
) -> float:
    """Extract a float value from *cfg*, falling back to *default*.

    Args:
        cfg: Configuration dictionary.
        key: Key to look up.
        default: Value returned when key is missing, ``None``, or invalid.
        warn: If ``True``, log a warning on invalid values.
        context: Optional context string included in the warning (e.g. module name).

    Returns:
        The extracted float, or *default* on failure.
    """
    val = cfg.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        if warn:
            ctx = f" [{context}]" if context else ""
            logger.warning(
                f"Invalid config value for {key!r}: {val!r} — using default {default}{ctx} ({exc})"
            )
        return default


def safe_get_int(
    cfg: Dict[str, Any],
    key: str,
    default: int = 0,
    *,
    warn: bool = True,
    context: str = "",
    lo: Optional[int] = None,
    hi: Optional[int] = None,
) -> int:
    """Extract an int value from *cfg*, falling back to *default*.

    Accepts float-like strings (e.g. ``"3.0"`` → ``3``).
    Optionally clamps the result to [lo, hi] range.

    Args:
        cfg: Configuration dictionary.
        key: Key to look up.
        default: Value returned when key is missing, ``None``, or invalid.
        warn: If ``True``, log a warning on invalid values.
        context: Optional context string included in the warning (e.g. module name).
        lo: Optional lower bound for clamping.
        hi: Optional upper bound for clamping.
    """
    val = cfg.get(key)
    if val is None:
        result = default
    else:
        try:
            result = int(float(val))
        except (TypeError, ValueError) as exc:
            if warn:
                ctx = f" [{context}]" if context else ""
                logger.warning(
                    f"Invalid config value for {key!r}: {val!r} — using default {default}{ctx} ({exc})"
                )
            result = default
    
    # Apply clamping if bounds specified
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    
    return result


def safe_get_bool(
    cfg: Dict[str, Any],
    key: str,
    default: bool = False,
    *,
    warn: bool = True,
    context: str = "",
) -> bool:
    """Extract a bool value from *cfg*, falling back to *default*.

    Accepts string representations: ``"true"``, ``"false"``, ``"1"``, ``"0"``,
    ``"yes"``, ``"no"`` (case-insensitive).
    """
    val = cfg.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        lower = val.strip().lower()
        if lower in ("true", "1", "yes", "on"):
            return True
        if lower in ("false", "0", "no", "off", ""):
            return False
    if warn:
        ctx = f" [{context}]" if context else ""
        logger.warning(
            f"Invalid config value for {key!r}: {val!r} — using default {default}{ctx}"
        )
    return default


def safe_get_str(
    cfg: Dict[str, Any],
    key: str,
    default: str = "",
    *,
    warn: bool = False,
    context: str = "",
) -> str:
    """Extract a string value from *cfg*, falling back to *default*.

    Non-string values are converted via ``str()``.  ``warn`` defaults to
    ``False`` because string conversion almost never fails.
    """
    val = cfg.get(key)
    if val is None:
        return default
    try:
        return str(val)
    except Exception as exc:
        if warn:
            ctx = f" [{context}]" if context else ""
            logger.warning(
                f"Invalid config value for {key!r}: {val!r} — using default {default!r}{ctx} ({exc})"
            )
        return default


def safe_cast(
    value: Any,
    cast_fn: type,
    default: Any = None,
    *,
    warn: bool = True,
    label: str = "",
) -> Any:
    """Generic safe-cast helper.

    Attempts ``cast_fn(value)`` and returns *default* on failure.

    Args:
        value: Value to cast.
        cast_fn: Callable that performs the cast (e.g. ``float``, ``int``).
        default: Fallback value.
        warn: If ``True``, log a warning on failure.
        label: Optional label for the warning message.

    Returns:
        The cast value, or *default* on failure.
    """
    if value is None:
        return default
    try:
        return cast_fn(value)
    except Exception as exc:
        if warn:
            lbl = f" ({label})" if label else ""
            logger.warning(
                f"Failed to cast {value!r} via {cast_fn.__name__}{lbl} — using default {default!r}: {exc}"
            )
        return default
