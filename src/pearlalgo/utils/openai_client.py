"""
OpenAI Client - Wrapper for OpenAI API.

Provides a simple interface to call OpenAI for code generation tasks,
specifically for generating unified diff patches.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.absolute_mode import ABSOLUTE_MODE_PROMPT


# ---------------------------------------------------------------------------
# Graceful optional import (openai is in the [llm] extra)
# ---------------------------------------------------------------------------

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4o"
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
+  new_line_added
   existing_line3

If multiple files need changes, include all of them in the same diff output."""


CHAT_SYSTEM_PROMPT = (
    ABSOLUTE_MODE_PROMPT
    + "\n\nROLE: AI assistant for the PearlAlgo MNQ Trading Agent inside Telegram.\n"
      "Scope\n"
      "- Trading system analysis, performance diagnosis, and configuration changes\n"
      "- Monitoring interpretation and fault isolation\n"
      "- Codebase debugging and minimal change guidance\n"
      "- Strategy and risk control adjustments for MNQ/NQ\n\n"
      "Constraints\n"
      "- Treat SYSTEM SNAPSHOT as authoritative.\n"
      "- If required data is missing, output MISSING list and stop.\n"
      "- Never output secrets or request them."
)


def build_chat_system_prompt(
    system_snapshot: Optional[str] = None,
    memory_summary: Optional[str] = None,
) -> str:
    """
    Build the chat system prompt, optionally appending a compact runtime snapshot.

    Args:
        memory_summary: A short, durable operator memory (goals, decisions, preferences)
        system_snapshot: A short, read-only context block (e.g., agent status, performance, recent signals)
    """
    prompt = CHAT_SYSTEM_PROMPT.strip()
    if memory_summary:
        mem = str(memory_summary).strip()
        if mem:
            prompt += "\n\nOPERATOR MEMORY (durable, do not overwrite with guesses):\n" + mem
    if system_snapshot:
        snapshot = str(system_snapshot).strip()
        if snapshot:
            prompt += "\n\nSYSTEM SNAPSHOT (read-only):\n" + snapshot
    return prompt


FILE_SUGGEST_SYSTEM_PROMPT = """You are a file suggestion assistant. Given a task description and a list of available files in a codebase, identify which files are most likely relevant to the task.

Return a JSON array of file paths, ordered by relevance (most relevant first). Include at most 8 files.

Example output:
["src/pearlalgo/utils/retry.py", "src/pearlalgo/nq_agent/main.py"]

ONLY output the JSON array, nothing else. No explanations, no markdown."""


class OpenAIClientError(Exception):
    """Base exception for OpenAI client errors."""
    pass


class OpenAINotAvailableError(OpenAIClientError):
    """Raised when openai package is not installed."""
    pass


class OpenAIAPIKeyMissingError(OpenAIClientError):
    """Raised when OPENAI_API_KEY is not set."""
    pass


class OpenAIAPIError(OpenAIClientError):
    """Raised when the OpenAI API returns an error."""
    pass


class OpenAIClient:
    """
    Client for interacting with OpenAI API.

    Usage:
        client = OpenAIClient()
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
        Initialize the OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (defaults to OPENAI_MODEL env var or gpt-4o)
            max_tokens: Max response tokens (defaults to OPENAI_MAX_TOKENS or 4096)
            timeout: Request timeout in seconds (defaults to OPENAI_TIMEOUT or 120)

        Raises:
            OpenAINotAvailableError: If openai package is not installed
            OpenAIAPIKeyMissingError: If API key is not provided or found in env
        """
        if not OPENAI_AVAILABLE:
            raise OpenAINotAvailableError(
                "openai package not installed. Install with: pip install -e .[llm]"
            )

        # Get API key (never log it)
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise OpenAIAPIKeyMissingError(
                "OPENAI_API_KEY not set. Add it to your .env file."
            )

        # Get configuration from env or use defaults
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)

        max_tokens_env = os.getenv("OPENAI_MAX_TOKENS")
        self._max_tokens = max_tokens or (int(max_tokens_env) if max_tokens_env else DEFAULT_MAX_TOKENS)

        timeout_env = os.getenv("OPENAI_TIMEOUT")
        self._timeout = timeout or (float(timeout_env) if timeout_env else DEFAULT_TIMEOUT)

        # Initialize client
        self._client = OpenAI(
            api_key=self._api_key,
            timeout=self._timeout,
        )

        # Circuit breaker: if the API reports low credits / billing issues,
        # temporarily disable calls to avoid spamming logs and wasting cycles.
        self._disabled_until: Optional[datetime] = None
        self._disabled_reason: Optional[str] = None

        logger.info(
            "OpenAI client initialized",
            extra={"model": self._model, "max_tokens": self._max_tokens, "timeout": self._timeout}
        )

    def _is_disabled(self) -> bool:
        """Return True if the circuit breaker is currently active."""
        if self._disabled_until is None:
            return False
        return datetime.now(timezone.utc) < self._disabled_until

    def _disable_for(self, seconds: int, reason: str) -> None:
        """Activate circuit breaker for N seconds (best-effort)."""
        try:
            self._disabled_until = datetime.now(timezone.utc) + timedelta(seconds=int(seconds))
            self._disabled_reason = str(reason)[:200]
            logger.warning(
                f"OpenAI client temporarily disabled for {seconds}s: {self._disabled_reason}",
                extra={"disabled_until": self._disabled_until.isoformat()},
            )
        except Exception:
            pass

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
            OpenAIAPIError: If the API request fails
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

        if self._is_disabled():
            raise OpenAIAPIError(
                f"OpenAI temporarily disabled until {self._disabled_until.isoformat() if self._disabled_until else 'unknown'}: "
                f"{self._disabled_reason or 'billing/availability issue'}"
            )

        logger.info(
            "Requesting patch from OpenAI",
            extra={"files": list(files.keys()), "task_preview": task[:100]}
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": PATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
            )

            # Extract text from response
            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                if result:
                    logger.info(
                        "Received patch from OpenAI",
                        extra={"response_length": len(result), "finish_reason": response.choices[0].finish_reason}
                    )
                    return result
            raise OpenAIAPIError("Empty response from OpenAI API")

        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                logger.error(f"OpenAI API rate limit: {e}")
                raise OpenAIAPIError(f"Rate limit exceeded: {e}") from e
            elif "insufficient_quota" in error_msg or "billing" in error_msg:
                logger.error(f"OpenAI API billing/quota error: {e}")
                self._disable_for(6 * 3600, reason=str(e))
                raise OpenAIAPIError(f"Billing/quota error: {e}") from e
            else:
                logger.error(f"Unexpected error calling OpenAI: {e}")
                raise OpenAIAPIError(f"Unexpected error: {e}") from e

    def is_available(self) -> bool:
        """Check if the client is ready to make API calls."""
        return OPENAI_AVAILABLE and bool(self._api_key) and not self._is_disabled()

    def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Send a chat message to OpenAI and get a response.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      Roles should be 'user' or 'assistant'.
            system_prompt: Optional system prompt (defaults to CHAT_SYSTEM_PROMPT)

        Returns:
            OpenAI's response text

        Raises:
            OpenAIAPIError: If the API request fails
        """
        system = system_prompt or CHAT_SYSTEM_PROMPT

        if self._is_disabled():
            raise OpenAIAPIError(
                f"OpenAI temporarily disabled until {self._disabled_until.isoformat() if self._disabled_until else 'unknown'}: "
                f"{self._disabled_reason or 'billing/availability issue'}"
            )

        logger.info(
            "Sending chat to OpenAI",
            extra={"message_count": len(messages)}
        )

        # Convert messages to OpenAI format and prepend system prompt
        openai_messages = [{"role": "system", "content": system}]
        for msg in messages:
            openai_messages.append({"role": msg["role"], "content": msg["content"]})

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=openai_messages,
            )

            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                if result:
                    logger.info(
                        "Received chat response from OpenAI",
                        extra={"response_length": len(result), "finish_reason": response.choices[0].finish_reason}
                    )
                    return result
            raise OpenAIAPIError("Empty response from OpenAI API")

        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                logger.error(f"OpenAI API rate limit: {e}")
                raise OpenAIAPIError(f"Rate limit exceeded: {e}") from e
            elif "insufficient_quota" in error_msg or "billing" in error_msg:
                logger.error(f"OpenAI API billing/quota error: {e}")
                self._disable_for(6 * 3600, reason=str(e))
                raise OpenAIAPIError(f"Billing/quota error: {e}") from e
            else:
                logger.error(f"Unexpected error calling OpenAI: {e}")
                raise OpenAIAPIError(f"Unexpected error: {e}") from e

    def generate_response(
        self,
        prompt: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate a single response from a user prompt.
        """
        system = system_prompt or CHAT_SYSTEM_PROMPT
        user_message = str(prompt)

        if self._is_disabled():
            raise OpenAIAPIError(
                f"OpenAI temporarily disabled until {self._disabled_until.isoformat() if self._disabled_until else 'unknown'}: "
                f"{self._disabled_reason or 'billing/availability issue'}"
            )

        logger.info(
            "Sending single-prompt request to OpenAI",
            extra={"prompt_preview": user_message[:100]}
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )

            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                if result:
                    logger.info(
                        "Received single-prompt response from OpenAI",
                        extra={"response_length": len(result), "finish_reason": response.choices[0].finish_reason}
                    )
                    return result
            raise OpenAIAPIError("Empty response from OpenAI API")

        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                logger.error(f"OpenAI API rate limit: {e}")
                raise OpenAIAPIError(f"Rate limit exceeded: {e}") from e
            if "insufficient_quota" in error_msg or "billing" in error_msg:
                logger.error(f"OpenAI API billing/quota error: {e}")
                self._disable_for(6 * 3600, reason=str(e))
                raise OpenAIAPIError(f"Billing/quota error: {e}") from e
            logger.error(f"Unexpected error calling OpenAI: {e}")
            raise OpenAIAPIError(f"Unexpected error: {e}") from e

    def suggest_files(
        self,
        task: str,
        available_files: list[str],
    ) -> list[str]:
        """
        Ask OpenAI to suggest relevant files for a task.

        Args:
            task: Description of the change/task
            available_files: List of available file paths

        Returns:
            List of suggested file paths (ordered by relevance)

        Raises:
            OpenAIAPIError: If the API request fails
        """
        import json

        # Limit file list to avoid token overflow
        files_preview = available_files[:500]

        user_message = f"""TASK: {task}

AVAILABLE FILES:
{chr(10).join(files_preview)}

Which files are most relevant to this task? Return a JSON array of file paths."""

        logger.info(
            "Requesting file suggestions from OpenAI",
            extra={"task_preview": task[:100], "file_count": len(files_preview)}
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": FILE_SUGGEST_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
            )

            if response.choices and len(response.choices) > 0:
                result = response.choices[0].message.content
                if result:
                    result = result.strip()
                    # Parse JSON array
                    try:
                        suggested = json.loads(result)
                        if isinstance(suggested, list):
                            # Filter to only include files that actually exist in our list
                            valid = [f for f in suggested if f in available_files]
                            logger.info(f"OpenAI suggested {len(valid)} files")
                            return valid[:8]
                    except json.JSONDecodeError:
                        logger.warning(f"Could not parse OpenAI file suggestions: {result[:200]}")
                        return []

            return []

        except Exception as e:
            logger.error(f"Error getting file suggestions: {e}")
            return []


def get_openai_client() -> Optional[OpenAIClient]:
    """
    Factory function to get an OpenAI client instance.

    Returns:
        OpenAIClient instance if available and configured, None otherwise.
    """
    if not OPENAI_AVAILABLE:
        logger.debug("OpenAI not available: openai package not installed")
        return None

    if not os.getenv("OPENAI_API_KEY"):
        logger.debug("OpenAI not available: OPENAI_API_KEY not set")
        return None

    try:
        return OpenAIClient()
    except OpenAIClientError as e:
        logger.warning(f"Could not initialize OpenAI client: {e}")
        return None
