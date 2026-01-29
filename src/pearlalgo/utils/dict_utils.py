"""
Dictionary utility functions.

Provides canonical implementations for common dictionary operations.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries. Override values take precedence.
    
    This is a pure function that returns a new dictionary without mutating inputs.

    Args:
        base: Base dictionary
        override: Dictionary with override values

    Returns:
        New merged dictionary (inputs are not modified)
    
    Example:
        >>> base = {"a": {"x": 1, "y": 2}, "b": 3}
        >>> override = {"a": {"y": 20, "z": 30}, "c": 4}
        >>> deep_merge(base, override)
        {"a": {"x": 1, "y": 20, "z": 30}, "b": 3, "c": 4}
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def deep_merge_inplace(dst: Dict[str, Any], src: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge src into dst (mutates dst).
    
    This is the mutating version for performance-critical code paths.

    Args:
        dst: Destination dictionary (will be mutated)
        src: Source dictionary to merge from

    Returns:
        The mutated dst dictionary
    
    Example:
        >>> dst = {"a": {"x": 1}}
        >>> src = {"a": {"y": 2}}
        >>> deep_merge_inplace(dst, src)
        >>> dst  # {"a": {"x": 1, "y": 2}}
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge_inplace(dst[k], v)  # type: ignore[index]
        else:
            dst[k] = v
    return dst
