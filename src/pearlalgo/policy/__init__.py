"""
Policy layer (platform core).

Goal: centralize all decision rules so we don't duplicate logic across:
- scanner
- signal_generator
- risk sizing/stops
- execution guards

This is the "forever" layer: new strategies and adapters should plug into this,
not re-implement policy logic ad-hoc.
"""

from .signal_policy import SignalPolicy, SignalPolicyDecision

__all__ = [
    "SignalPolicy",
    "SignalPolicyDecision",
]


