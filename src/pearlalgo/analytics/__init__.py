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
from pearlalgo.analytics.session_analytics import (
    compute_session_analytics,
)
from pearlalgo.analytics.incident_analysis import (
    build_incident_report,
    compute_exposure,
    group_stats,
)

__all__ = [
    "TradeRecord",
    "SummaryRow",
    "build_report",
    "build_doctor_rollup",
    "format_doctor_rollup_text",
    "compute_session_analytics",
    "build_incident_report",
    "compute_exposure",
    "group_stats",
]
