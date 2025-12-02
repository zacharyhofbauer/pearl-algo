"""
Futures-focused utilities: config, contracts, signals, risk, and performance logging.
"""

from .config import DEFAULT_PROP_PROFILE, PropProfile, load_profile
from .contracts import (
    FUTURES_METADATA,
    available_symbols,
    es_contract,
    fut_contract,
    gc_contract,
    nq_contract,
)
from .performance import (
    DEFAULT_PERF_PATH,
    PerformanceRow,
    load_performance,
    log_performance_row,
    summarize_daily_performance,
)
from .risk import RiskState, compute_position_size, compute_risk_state
from .signals import generate_signal, ma_cross_signal

__all__ = [
    "PropProfile",
    "DEFAULT_PROP_PROFILE",
    "load_profile",
    "FUTURES_METADATA",
    "available_symbols",
    "fut_contract",
    "es_contract",
    "nq_contract",
    "gc_contract",
    "PerformanceRow",
    "DEFAULT_PERF_PATH",
    "log_performance_row",
    "load_performance",
    "summarize_daily_performance",
    "RiskState",
    "compute_position_size",
    "compute_risk_state",
    "generate_signal",
    "ma_cross_signal",
]
