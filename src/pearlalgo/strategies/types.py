"""
Strategy interfaces and shared typing helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol

import pandas as pd


SignalDict = dict[str, Any]


@dataclass(frozen=True)
class StrategyContext:
    """Minimal runtime context passed to strategy analyzers."""

    current_time: Optional[datetime] = None
    df_5m: Optional[pd.DataFrame] = None


class Strategy(Protocol):
    """Runtime contract for a live strategy bundle."""

    name: str

    def analyze(
        self,
        df: pd.DataFrame,
        *,
        current_time: Optional[datetime] = None,
        df_5m: Optional[pd.DataFrame] = None,
    ) -> list[SignalDict]:
        ...

    def default_config(self) -> Mapping[str, Any]:
        ...
