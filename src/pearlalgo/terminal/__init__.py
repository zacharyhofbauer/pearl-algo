"""
Pearl Terminal - Rich CLI interface for Pearl AI.

This module provides a terminal-based interface for interacting with Pearl AI,
featuring Claude-like thinking displays, real-time monitoring, and interactive chat.

Usage:
    # From command line:
    pearl chat "Why was the last signal filtered?"
    pearl monitor --show-thinking
    pearl analyze --trade T-2026-01-29-001
    pearl learn --report filter-effectiveness
    
    # Programmatically:
    from pearlalgo.terminal import PearlTerminalAgent
    
    agent = PearlTerminalAgent()
    await agent.chat("Analyze the current market conditions")
"""

from pearlalgo.terminal.agent import PearlTerminalAgent
from pearlalgo.terminal.display import (
    PearlDisplay,
    display_thinking,
    display_signal,
    display_trace,
)

__all__ = [
    "PearlTerminalAgent",
    "PearlDisplay",
    "display_thinking",
    "display_signal",
    "display_trace",
]
