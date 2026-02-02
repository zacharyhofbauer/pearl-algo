"""
Pearl AI 2.0 - Conversational Trading AI

A hybrid AI system that combines local LLM for quick responses
with Claude API for deep analysis and coaching.
"""

from .brain import PearlBrain
from .narrator import PearlNarrator
from .memory import PearlMemory

__all__ = ["PearlBrain", "PearlNarrator", "PearlMemory"]
__version__ = "2.0.0"
