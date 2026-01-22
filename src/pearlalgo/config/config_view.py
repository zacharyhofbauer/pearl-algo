"""Config wrapper utilities."""

from __future__ import annotations

from typing import Any


class ConfigView(dict):
    """Dict wrapper that supports attribute access (config.key)."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value
