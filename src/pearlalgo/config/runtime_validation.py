"""
Shared runtime config validation for startup and control-plane writes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from pearlalgo.config.config_file import validate_config as collect_config_warnings
from pearlalgo.config.migration import migrate_legacy_runtime_config
from pearlalgo.config.schema_v2 import validate_config as validate_schema_v2


NON_ENFORCED_FLAG_PATHS = frozenset({
    "signals.skip_overnight",
    "signals.avoid_lunch_lull",
    "signals.prioritize_ny_session",
})


def _get_nested(config: Dict[str, Any], dotted_path: str) -> Any:
    current: Any = config
    for key in dotted_path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def find_non_enforced_flags(config: Dict[str, Any]) -> List[str]:
    """Return configured warn-only flags that currently have truthy values."""
    return sorted(
        path for path in NON_ENFORCED_FLAG_PATHS
        if bool(_get_nested(config, path))
    )


def validate_runtime_config(
    raw: Dict[str, Any],
    *,
    strict_non_enforced: bool = False,
    warn_unknown: bool = True,
) -> Dict[str, Any]:
    """
    Validate canonical runtime config and return the normalized dict.

    This is the shared validation path for startup and config mutation APIs.
    """
    normalized = migrate_legacy_runtime_config(raw or {})
    blocked_paths = find_non_enforced_flags(normalized)
    validated = validate_schema_v2(normalized)

    if warn_unknown:
        # Run lightweight warning checks for operator visibility. Callers decide
        # whether and how to surface the returned warnings.
        collect_config_warnings(validated, warn_unknown=True)

    if strict_non_enforced:
        if blocked_paths:
            paths = ", ".join(blocked_paths)
            raise ValueError(
                f"Config contains warn-only fields that are not enforced at runtime: {paths}"
            )

    return validated


def collect_runtime_config_warnings(
    raw: Dict[str, Any],
    *,
    warn_unknown: bool = True,
) -> List[str]:
    """Collect non-fatal config warnings for UI/logging surfaces."""
    normalized = migrate_legacy_runtime_config(raw or {})
    warnings = collect_config_warnings(normalized, warn_unknown=warn_unknown)
    blocked_paths = find_non_enforced_flags(normalized)
    for path in blocked_paths:
        warnings.append(f"{path} is configured but not enforced at runtime.")
    return warnings
