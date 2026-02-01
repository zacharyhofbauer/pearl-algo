"""
Pearl AI - Conversational AI and intelligent insights for PEARLalgo.

This module provides:
- PearlAIChat: Conversational AI via Telegram /pearl command
- AI-powered briefings and insights for automated notifications
- PearlShadowTracker: Shadow tracking for AI suggestion outcomes
"""

from pearlalgo.ai.chat import PearlAIChat, get_ai_chat
from pearlalgo.ai.shadow_tracker import (
    PearlShadowTracker,
    get_shadow_tracker,
    SuggestionType,
    SuggestionOutcome,
)

__all__ = [
    "PearlAIChat",
    "get_ai_chat",
    "PearlShadowTracker",
    "get_shadow_tracker",
    "SuggestionType",
    "SuggestionOutcome",
]
