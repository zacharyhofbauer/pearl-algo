"""
Prop firm rule enforcement helpers.

This package provides an optional "prop firm mode" that can:
- Gate automated execution (ATS) based on firm rules (drawdown, max contracts, etc.)
- Annotate signals with compliance info for manual trading workflows

It is intentionally broker-agnostic and reads only local state files written by the agent.
"""

from __future__ import annotations



