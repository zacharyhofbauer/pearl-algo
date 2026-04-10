"""
Canonical live strategy bundle: composite_intraday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

import pandas as pd

from pearlalgo.strategies.composite_intraday import pinescript_core


@dataclass
class CompositeIntradayStrategy:
    """Compatibility-backed live strategy bundle."""

    config: Mapping[str, Any]
    name: str = "composite_intraday"

    def analyze(
        self,
        df: pd.DataFrame,
        *,
        current_time: Optional[datetime] = None,
        df_5m: Optional[pd.DataFrame] = None,
        diagnostics: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        return pinescript_core.generate_signals(
            df,
            config=dict(self.config),
            current_time=current_time,
            df_5m=df_5m,
            diagnostics=diagnostics,
        )

    def default_config(self) -> Mapping[str, Any]:
        return pinescript_core.default_config()
