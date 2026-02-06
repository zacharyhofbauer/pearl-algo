"""
Prompt Loader - Loads versioned YAML prompt templates.

Prompts are stored as YAML files in this directory, loaded once at init,
and accessed by name. Inline fallbacks ensure the system never fails
to start due to a missing prompt file.
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class PromptRegistry:
    """
    Registry of versioned prompt templates.

    Loads all prompt YAML files from the prompts directory on init.
    Provides get() access by prompt name with inline fallback support.
    """

    def __init__(self) -> None:
        self._prompts: Dict[str, Dict[str, Any]] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all YAML prompt files from the prompts directory."""
        try:
            import yaml  # noqa: F811
        except ImportError:
            # PyYAML not installed -- fall back to built-in parsing
            logger.warning("PyYAML not installed; prompts will use inline fallbacks")
            return

        for yaml_file in sorted(PROMPTS_DIR.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                for key, value in data.items():
                    if isinstance(value, dict) and "template" in value:
                        self._prompts[key] = value
                logger.debug(f"Loaded prompts from {yaml_file.name}")
            except Exception as exc:
                logger.warning(f"Failed to load prompt file {yaml_file}: {exc}")

        if self._prompts:
            logger.info(f"Loaded {len(self._prompts)} prompt templates")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str, fallback: Optional[str] = None) -> str:
        """
        Get a prompt template by name.

        Args:
            name: Prompt identifier (e.g. ``deep_system``, ``trade_entered``)
            fallback: Inline fallback string if prompt not found in YAML.

        Returns:
            The prompt template string.
        """
        entry = self._prompts.get(name)
        if entry:
            return entry["template"]
        if fallback is not None:
            return fallback
        raise KeyError(f"Prompt '{name}' not found and no fallback provided")

    def get_version(self, name: str) -> str:
        """Get the version tag for a prompt (or 'inline' if from fallback)."""
        entry = self._prompts.get(name)
        if entry:
            return str(entry.get("version", "unknown"))
        return "inline"

    def get_metadata(self, name: str) -> Dict[str, Any]:
        """Get full metadata dict for a prompt."""
        return dict(self._prompts.get(name, {}))

    def list_prompts(self) -> list[str]:
        """Return all loaded prompt names."""
        return sorted(self._prompts.keys())

    def has(self, name: str) -> bool:
        """Check if a prompt is loaded."""
        return name in self._prompts


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[PromptRegistry] = None


def get_prompt_registry() -> PromptRegistry:
    """Get or create the global prompt registry."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
