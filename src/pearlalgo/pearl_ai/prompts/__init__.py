"""
Pearl AI Prompts - Versioned, externalized prompt templates.

All system prompts and narration templates live here, loaded at init time.
This enables independent review, diff, A/B testing, and rollback of prompts
without touching orchestration code.
"""

from .loader import PromptRegistry, get_prompt_registry

__all__ = ["PromptRegistry", "get_prompt_registry"]
