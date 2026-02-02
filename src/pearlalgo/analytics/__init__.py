"""
PearlAlgo Analytics Module

Business logic for strategy analysis, reporting, and diagnostics.
"""

from pearlalgo.analytics.strategy_report import (
    TradeRecord,
    SummaryRow,
    build_report,
)
from pearlalgo.analytics.doctor_report import (
    build_doctor_rollup,
    format_doctor_rollup_text,
)

__all__ = [
    "TradeRecord",
    "SummaryRow",
    "build_report",
    "build_doctor_rollup",
    "format_doctor_rollup_text",
]
