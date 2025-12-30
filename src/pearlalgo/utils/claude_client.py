"""
Claude Client - Wrapper for Anthropic API.

Provides a simple interface to call Claude for code generation tasks,
specifically for generating unified diff patches.
"""

from __future__ import annotations

import os
from typing import Optional

from pearlalgo.utils.logger import logger


# ---------------------------------------------------------------------------
# Graceful optional import (anthropic is in the [llm] extra)
# ---------------------------------------------------------------------------

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore
    ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT = 120  # seconds


# ---------------------------------------------------------------------------
# System prompt for patch generation
# ---------------------------------------------------------------------------

PATCH_SYSTEM_PROMPT = """You are a senior software engineer. Your task is to generate code changes as a unified diff patch.

RULES:
1. Output ONLY the unified diff patch - no explanations, no markdown, no code blocks.
2. Use standard unified diff format with --- and +++ headers.
3. Include proper context lines (at least 3 lines before/after changes).
4. Be precise and minimal - only change what's needed for the task.
5. Preserve existing code style (indentation, quotes, etc.).
6. Never add unnecessary changes or "improvements" beyond the requested task.

Example output format:
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -10,6 +10,7 @@ def existing_function():
    existing_line1
    existing_line2
+    new_line_added
    existing_line3

If multiple files need changes, include all of them in the same diff output."""


CHAT_SYSTEM_PROMPT = """You are Claude, an AI assistant integrated into a Telegram bot for a trading system development project (PearlAlgo MNQ Trading Agent).

You're acting as a mobile Cursor-style assistant. The user is likely on their phone and wants quick, helpful responses.

CONTEXT:
- This is a Python trading system with IBKR integration, Telegram notifications, and signal generation.
- Key directories: src/pearlalgo/ (source), tests/, scripts/, docs/, config/
- The codebase follows strict module boundaries (utils -> config -> data_providers -> strategies -> nq_agent).

GUIDELINES:
1. Be concise - the user is on mobile.
2. When discussing code, mention file paths so the user knows where to look.
3. For code changes, suggest using the Patch wizard (available in the Claude menu).
4. You can help with: debugging, explaining code, architecture questions, planning changes, reviewing approaches.
5. Don't generate long code blocks - suggest patches instead for actual changes.
6. If you need to see specific files, ask the user to use the Patch wizard which can show file contents.

Be helpful, direct, and practical."""


FILE_SUGGEST_SYSTEM_PROMPT = """You are a file suggestion assistant. Given a task description and a list of available files in a codebase, identify which files are most likely relevant to the task.

Return a JSON array of file paths, ordered by relevance (most relevant first). Include at most 8 files.

Example output:
["src/pearlalgo/utils/retry.py", "src/pearlalgo/nq_agent/main.py"]

ONLY output the JSON array, nothing else. No explanations, no markdown."""


class ClaudeClientError(Exception):
    """Base exception for Claude client errors."""
    pass


class ClaudeNotAvailableError(ClaudeClientError):
    """Raised when anthropic package is not installed."""
    pass


class ClaudeAPIKeyMissingError(ClaudeClientError):
    """Raised when ANTHROPIC_API_KEY is not set."""
    pass


class ClaudeAPIError(ClaudeClientError):
    """Raised when the Anthropic API returns an error."""
    pass


class ClaudeClient:
    """
    Client for interacting with Claude via the Anthropic API.
    
    Usage:
        client = ClaudeClient()
        diff = client.generate_patch(
            files={"src/foo.py": "def foo(): pass"},
            task="Add a docstring to foo()"
        )
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ):
        """
        Initialize the Claude client.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use (defaults to ANTHROPIC_MODEL env var or claude-sonnet-4-20250514)
            max_tokens: Max response tokens (defaults to ANTHROPIC_MAX_TOKENS or 4096)
            timeout: Request timeout in seconds (defaults to ANTHROPIC_TIMEOUT or 120)
        
        Raises:
            ClaudeNotAvailableError: If anthropic package is not installed
            ClaudeAPIKeyMissingError: If API key is not provided or found in env
        """
        if not ANTHROPIC_AVAILABLE:
            raise ClaudeNotAvailableError(
                "anthropic package not installed. Install with: pip install -e .[llm]"
            )
        
        # Get API key (never log it)
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ClaudeAPIKeyMissingError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file."
            )
        
        # Get configuration from env or use defaults
        self._model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)
        
        max_tokens_env = os.getenv("ANTHROPIC_MAX_TOKENS")
        self._max_tokens = max_tokens or (int(max_tokens_env) if max_tokens_env else DEFAULT_MAX_TOKENS)
        
        timeout_env = os.getenv("ANTHROPIC_TIMEOUT")
        self._timeout = timeout or (float(timeout_env) if timeout_env else DEFAULT_TIMEOUT)
        
        # Initialize client
        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=self._timeout,
        )
        
        logger.info(
            "Claude client initialized",
            extra={"model": self._model, "max_tokens": self._max_tokens, "timeout": self._timeout}
        )
    
    def generate_patch(
        self,
        files: dict[str, str],
        task: str,
        additional_context: Optional[str] = None,
    ) -> str:
        """
        Generate a unified diff patch for the given task.
        
        Args:
            files: Dictionary mapping file paths to their contents
            task: Description of the change to make
            additional_context: Optional extra context to include
        
        Returns:
            Unified diff patch as a string
        
        Raises:
            ClaudeAPIError: If the API request fails
        """
        # Build the user message
        user_message_parts = []
        
        # Add file contents
        user_message_parts.append("FILES TO MODIFY:\n")
        for path, content in files.items():
            # Truncate very long files to avoid token limits
            if len(content) > 50000:
                content = content[:50000] + "\n\n... (truncated, file too long)"
                logger.warning(f"File {path} truncated (>50k chars)")
            
            user_message_parts.append(f"--- {path} ---\n{content}\n")
        
        # Add task
        user_message_parts.append(f"\nTASK:\n{task}")
        
        # Add additional context if provided
        if additional_context:
            user_message_parts.append(f"\nADDITIONAL CONTEXT:\n{additional_context}")
        
        user_message = "\n".join(user_message_parts)
        
        logger.info(
            "Requesting patch from Claude",
            extra={"files": list(files.keys()), "task_preview": task[:100]}
        )
        
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=PATCH_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_message}
                ],
            )
            
            # Extract text from response
            if response.content and len(response.content) > 0:
                result = response.content[0].text
                logger.info(
                    "Received patch from Claude",
                    extra={"response_length": len(result), "stop_reason": response.stop_reason}
                )
                return result
            else:
                raise ClaudeAPIError("Empty response from Claude API")
                
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude API connection error: {e}")
            raise ClaudeAPIError(f"Connection error: {e}") from e
        except anthropic.RateLimitError as e:
            logger.error(f"Claude API rate limit: {e}")
            raise ClaudeAPIError(f"Rate limit exceeded: {e}") from e
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API status error: {e}")
            raise ClaudeAPIError(f"API error ({e.status_code}): {e.message}") from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude: {e}")
            raise ClaudeAPIError(f"Unexpected error: {e}") from e
    
    def is_available(self) -> bool:
        """Check if the client is ready to make API calls."""
        return ANTHROPIC_AVAILABLE and bool(self._api_key)
    
    def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send a chat message to Claude and get a response.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      Roles should be 'user' or 'assistant'.
            system_prompt: Optional system prompt (defaults to CHAT_SYSTEM_PROMPT)
        
        Returns:
            Claude's response text
        
        Raises:
            ClaudeAPIError: If the API request fails
        """
        system = system_prompt or CHAT_SYSTEM_PROMPT
        
        logger.info(
            "Sending chat to Claude",
            extra={"message_count": len(messages)}
        )
        
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
            )
            
            if response.content and len(response.content) > 0:
                result = response.content[0].text
                logger.info(
                    "Received chat response from Claude",
                    extra={"response_length": len(result), "stop_reason": response.stop_reason}
                )
                return result
            else:
                raise ClaudeAPIError("Empty response from Claude API")
                
        except anthropic.APIConnectionError as e:
            logger.error(f"Claude API connection error: {e}")
            raise ClaudeAPIError(f"Connection error: {e}") from e
        except anthropic.RateLimitError as e:
            logger.error(f"Claude API rate limit: {e}")
            raise ClaudeAPIError(f"Rate limit exceeded: {e}") from e
        except anthropic.APIStatusError as e:
            logger.error(f"Claude API status error: {e}")
            raise ClaudeAPIError(f"API error ({e.status_code}): {e.message}") from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude: {e}")
            raise ClaudeAPIError(f"Unexpected error: {e}") from e
    
    def suggest_files(
        self,
        task: str,
        available_files: list[str],
    ) -> list[str]:
        """
        Ask Claude to suggest relevant files for a task.
        
        Args:
            task: Description of the change/task
            available_files: List of available file paths
        
        Returns:
            List of suggested file paths (ordered by relevance)
        
        Raises:
            ClaudeAPIError: If the API request fails
        """
        import json
        
        # Limit file list to avoid token overflow
        files_preview = available_files[:500]
        
        user_message = f"""TASK: {task}

AVAILABLE FILES:
{chr(10).join(files_preview)}

Which files are most relevant to this task? Return a JSON array of file paths."""
        
        logger.info(
            "Requesting file suggestions from Claude",
            extra={"task_preview": task[:100], "file_count": len(files_preview)}
        )
        
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=FILE_SUGGEST_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            
            if response.content and len(response.content) > 0:
                result = response.content[0].text.strip()
                # Parse JSON array
                try:
                    suggested = json.loads(result)
                    if isinstance(suggested, list):
                        # Filter to only include files that actually exist in our list
                        valid = [f for f in suggested if f in available_files]
                        logger.info(f"Claude suggested {len(valid)} files")
                        return valid[:8]
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse Claude file suggestions: {result[:200]}")
                    return []
            
            return []
                
        except Exception as e:
            logger.error(f"Error getting file suggestions: {e}")
            return []


def get_claude_client() -> Optional[ClaudeClient]:
    """
    Factory function to get a Claude client instance.
    
    Returns:
        ClaudeClient instance if available and configured, None otherwise.
    """
    if not ANTHROPIC_AVAILABLE:
        logger.debug("Claude not available: anthropic package not installed")
        return None
    
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.debug("Claude not available: ANTHROPIC_API_KEY not set")
        return None
    
    try:
        return ClaudeClient()
    except ClaudeClientError as e:
        logger.warning(f"Could not initialize Claude client: {e}")
        return None

