"""
Suggestion Engine - Generates actionable recommendations from analysis.

Converts analysis findings into concrete suggestions for configuration
tuning, code improvements, and operational changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


class SuggestionType(Enum):
    """Types of suggestions."""
    CONFIG_CHANGE = "config_change"      # Modify config.yaml
    CODE_PATCH = "code_patch"            # Generate code diff
    SERVICE_ACTION = "service_action"    # Restart, etc.
    PARAMETER_TUNE = "parameter_tune"    # Specific parameter adjustment
    INVESTIGATION = "investigation"       # Manual investigation needed


class SuggestionPriority(Enum):
    """Suggestion priority levels."""
    HIGH = "high"        # Should be applied soon
    MEDIUM = "medium"    # Consider applying
    LOW = "low"          # Optional improvement


@dataclass
class Suggestion:
    """Represents an actionable suggestion."""
    type: SuggestionType
    priority: SuggestionPriority
    title: str
    description: str
    rationale: str
    category: str  # signals, system, market, code
    source: str    # analyzer that generated it
    timestamp: str = field(default_factory=get_utc_timestamp)
    
    # For config changes
    config_path: Optional[str] = None  # e.g., "signals.min_confidence"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    
    # For code patches
    files: Optional[List[str]] = None
    patch_task: Optional[str] = None
    
    # For service actions
    action: Optional[str] = None  # restart, reconfigure, etc.
    
    # Impact assessment
    expected_impact: Optional[str] = None
    risk_level: Optional[str] = None  # low, medium, high
    reversible: bool = True
    
    # Metadata
    analysis_data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "rationale": self.rationale,
            "category": self.category,
            "source": self.source,
            "timestamp": self.timestamp,
            "config_path": self.config_path,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "files": self.files,
            "patch_task": self.patch_task,
            "action": self.action,
            "expected_impact": self.expected_impact,
            "risk_level": self.risk_level,
            "reversible": self.reversible,
        }
    
    def format_telegram(self) -> str:
        """Format suggestion for Telegram message."""
        priority_emoji = {
            SuggestionPriority.HIGH: "🔺",
            SuggestionPriority.MEDIUM: "🔸",
            SuggestionPriority.LOW: "🔹",
        }
        
        lines = [
            f"💡 *Suggestion: {self.title}*",
            "",
            f"{priority_emoji.get(self.priority, '•')} Priority: {self.priority.value}",
            f"📁 Category: {self.category}",
            f"🔧 Type: {self.type.value.replace('_', ' ')}",
            "",
            f"*Description:*\n{self.description}",
            "",
            f"*Rationale:*\n{self.rationale}",
        ]
        
        if self.config_path and self.new_value is not None:
            lines.extend([
                "",
                "*Proposed Change:*",
                f"`{self.config_path}`",
                f"Current: `{self.old_value}`",
                f"New: `{self.new_value}`",
            ])
        
        if self.expected_impact:
            lines.extend(["", f"*Expected Impact:* {self.expected_impact}"])
        
        if self.risk_level:
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
            lines.append(f"*Risk:* {risk_emoji.get(self.risk_level, '•')} {self.risk_level}")
        
        return "\n".join(lines)


class SuggestionEngine:
    """
    Generates actionable suggestions from analysis results.
    
    Uses Claude to:
    - Identify optimization opportunities
    - Generate specific recommendations
    - Assess impact and risk
    - Prioritize suggestions
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
        max_suggestions_per_analysis: int = 5,
    ):
        """
        Initialize suggestion engine.
        
        Args:
            claude_client: Claude API client
            max_suggestions_per_analysis: Maximum suggestions per analysis cycle
        """
        self._claude = claude_client
        self.max_suggestions = max_suggestions_per_analysis
        
        # Track recent suggestions to avoid repetition
        self._recent_suggestions: Dict[str, datetime] = {}
    
    def set_claude_client(self, client: "ClaudeClient") -> None:
        """Set or update the Claude client."""
        self._claude = client
    
    def generate(
        self,
        analysis: Dict[str, Any],
    ) -> List[Suggestion]:
        """
        Generate suggestions from analysis results.
        
        Args:
            analysis: Analysis results from all dimensions
            
        Returns:
            List of actionable suggestions
        """
        suggestions = []
        
        # Generate suggestions for each dimension
        for dimension, result in analysis.items():
            if not isinstance(result, dict):
                continue
            
            # Skip if analysis had errors
            if result.get("status") == "error":
                continue
            
            # Extract suggestions from analysis
            dimension_suggestions = self._extract_suggestions(result, dimension)
            suggestions.extend(dimension_suggestions)
        
        # Deduplicate and prioritize
        suggestions = self._deduplicate(suggestions)
        suggestions = self._prioritize(suggestions)
        
        # Limit to max suggestions
        return suggestions[:self.max_suggestions]
    
    def _extract_suggestions(
        self,
        result: Dict[str, Any],
        dimension: str,
    ) -> List[Suggestion]:
        """Extract suggestions from analysis result."""
        suggestions = []
        
        # Check for explicit suggestions in result
        if "suggestions" in result:
            for sug_data in result["suggestions"]:
                suggestion = self._create_suggestion(sug_data, dimension)
                if suggestion:
                    suggestions.append(suggestion)
        
        # Check for findings that warrant suggestions
        if "findings" in result:
            for finding in result.get("findings", []):
                suggestion = self._finding_to_suggestion(finding, dimension)
                if suggestion:
                    suggestions.append(suggestion)
        
        # Check for recommendations
        if "recommendations" in result:
            for rec in result["recommendations"]:
                suggestion = self._recommendation_to_suggestion(rec, dimension)
                if suggestion:
                    suggestions.append(suggestion)
        
        return suggestions
    
    def _create_suggestion(
        self,
        data: Dict[str, Any],
        dimension: str,
    ) -> Optional[Suggestion]:
        """Create a Suggestion from raw data."""
        try:
            sug_type = SuggestionType(data.get("type", "investigation"))
            priority = SuggestionPriority(data.get("priority", "medium"))
            
            return Suggestion(
                type=sug_type,
                priority=priority,
                title=data.get("title", "Suggestion"),
                description=data.get("description", ""),
                rationale=data.get("rationale", ""),
                category=data.get("category", dimension),
                source=dimension,
                config_path=data.get("config_path"),
                old_value=data.get("old_value"),
                new_value=data.get("new_value"),
                files=data.get("files"),
                patch_task=data.get("patch_task"),
                action=data.get("action"),
                expected_impact=data.get("expected_impact"),
                risk_level=data.get("risk_level", "low"),
                reversible=data.get("reversible", True),
                analysis_data=data.get("data"),
            )
        except Exception as e:
            logger.warning(f"Could not create suggestion: {e}")
            return None
    
    def _finding_to_suggestion(
        self,
        finding: Dict[str, Any],
        dimension: str,
    ) -> Optional[Suggestion]:
        """Convert a finding to a suggestion if actionable."""
        # Only convert high-impact findings
        severity = finding.get("severity", "info")
        if severity in ("low", "info"):
            return None
        
        # Check if finding has recommendation
        recommendation = finding.get("recommendation")
        if not recommendation:
            return None
        
        return Suggestion(
            type=SuggestionType.INVESTIGATION,
            priority=SuggestionPriority.MEDIUM if severity == "medium" else SuggestionPriority.HIGH,
            title=finding.get("title", finding.get("type", "Issue")),
            description=recommendation,
            rationale=finding.get("description", finding.get("message", "")),
            category=finding.get("category", dimension),
            source=dimension,
            expected_impact=finding.get("impact"),
            risk_level=finding.get("risk", "low"),
        )
    
    def _recommendation_to_suggestion(
        self,
        rec: Dict[str, Any],
        dimension: str,
    ) -> Optional[Suggestion]:
        """Convert a recommendation to a suggestion."""
        # Determine suggestion type from recommendation
        if "config_path" in rec:
            sug_type = SuggestionType.CONFIG_CHANGE
        elif "files" in rec:
            sug_type = SuggestionType.CODE_PATCH
        elif "action" in rec:
            sug_type = SuggestionType.SERVICE_ACTION
        else:
            sug_type = SuggestionType.INVESTIGATION
        
        return Suggestion(
            type=sug_type,
            priority=SuggestionPriority(rec.get("priority", "medium")),
            title=rec.get("title", "Recommendation"),
            description=rec.get("description", ""),
            rationale=rec.get("rationale", ""),
            category=rec.get("category", dimension),
            source=dimension,
            config_path=rec.get("config_path"),
            old_value=rec.get("old_value"),
            new_value=rec.get("new_value"),
            files=rec.get("files"),
            patch_task=rec.get("patch_task"),
            action=rec.get("action"),
            expected_impact=rec.get("expected_impact"),
            risk_level=rec.get("risk_level", "low"),
        )
    
    def _deduplicate(self, suggestions: List[Suggestion]) -> List[Suggestion]:
        """Remove duplicate suggestions."""
        seen = set()
        unique = []
        
        for sug in suggestions:
            # Create fingerprint
            if sug.config_path:
                key = f"config:{sug.config_path}"
            elif sug.files:
                key = f"code:{','.join(sug.files)}"
            elif sug.action:
                key = f"action:{sug.action}"
            else:
                key = f"title:{sug.title}"
            
            if key not in seen:
                seen.add(key)
                unique.append(sug)
        
        return unique
    
    def _prioritize(self, suggestions: List[Suggestion]) -> List[Suggestion]:
        """Sort suggestions by priority and impact."""
        def priority_key(sug: Suggestion) -> tuple:
            priority_order = {
                SuggestionPriority.HIGH: 0,
                SuggestionPriority.MEDIUM: 1,
                SuggestionPriority.LOW: 2,
            }
            type_order = {
                SuggestionType.SERVICE_ACTION: 0,
                SuggestionType.CONFIG_CHANGE: 1,
                SuggestionType.PARAMETER_TUNE: 2,
                SuggestionType.CODE_PATCH: 3,
                SuggestionType.INVESTIGATION: 4,
            }
            return (priority_order.get(sug.priority, 2), type_order.get(sug.type, 4))
        
        return sorted(suggestions, key=priority_key)
    
    async def generate_config_suggestion(
        self,
        finding: Dict[str, Any],
        current_config: Dict[str, Any],
    ) -> Optional[Suggestion]:
        """
        Use Claude to generate a specific config change suggestion.
        
        Args:
            finding: The finding that warrants config change
            current_config: Current configuration values
            
        Returns:
            Config change suggestion or None
        """
        if not self._claude:
            return None
        
        prompt = f"""Based on this analysis finding, suggest a specific configuration change:

FINDING:
{json.dumps(finding, indent=2)}

CURRENT CONFIG (relevant sections):
{json.dumps(current_config, indent=2)}

Respond with JSON:
{{
    "config_path": "path.to.config.key",
    "old_value": <current value>,
    "new_value": <suggested value>,
    "rationale": "Why this change helps",
    "expected_impact": "What improvement to expect",
    "risk_level": "low|medium|high"
}}

Only suggest changes if you're confident they will help. Return null if no change is warranted."""
        
        try:
            response = self._claude.chat([{"role": "user", "content": prompt}])
            data = json.loads(response)
            
            if data and data.get("config_path"):
                return Suggestion(
                    type=SuggestionType.CONFIG_CHANGE,
                    priority=SuggestionPriority.MEDIUM,
                    title=f"Tune {data['config_path']}",
                    description=f"Change {data['config_path']} from {data['old_value']} to {data['new_value']}",
                    rationale=data.get("rationale", ""),
                    category="config",
                    source="suggestion_engine",
                    config_path=data["config_path"],
                    old_value=data.get("old_value"),
                    new_value=data.get("new_value"),
                    expected_impact=data.get("expected_impact"),
                    risk_level=data.get("risk_level", "low"),
                )
        except Exception as e:
            logger.warning(f"Could not generate config suggestion: {e}")
        
        return None
    
    async def generate_code_suggestion(
        self,
        finding: Dict[str, Any],
        relevant_files: List[str],
    ) -> Optional[Suggestion]:
        """
        Use Claude to generate a code improvement suggestion.
        
        Args:
            finding: The finding that warrants code change
            relevant_files: List of potentially relevant files
            
        Returns:
            Code patch suggestion or None
        """
        if not self._claude:
            return None
        
        prompt = f"""Based on this analysis finding, suggest a code improvement:

FINDING:
{json.dumps(finding, indent=2)}

RELEVANT FILES:
{json.dumps(relevant_files, indent=2)}

Respond with JSON:
{{
    "files": ["list", "of", "files.py"],
    "patch_task": "Description of what to change",
    "rationale": "Why this change helps",
    "expected_impact": "What improvement to expect",
    "risk_level": "low|medium|high"
}}

Only suggest changes if you're confident they will help. Return null if no change is warranted."""
        
        try:
            response = self._claude.chat([{"role": "user", "content": prompt}])
            data = json.loads(response)
            
            if data and data.get("files"):
                return Suggestion(
                    type=SuggestionType.CODE_PATCH,
                    priority=SuggestionPriority.LOW,
                    title=f"Code improvement in {data['files'][0]}",
                    description=data.get("patch_task", ""),
                    rationale=data.get("rationale", ""),
                    category="code",
                    source="suggestion_engine",
                    files=data.get("files"),
                    patch_task=data.get("patch_task"),
                    expected_impact=data.get("expected_impact"),
                    risk_level=data.get("risk_level", "medium"),
                )
        except Exception as e:
            logger.warning(f"Could not generate code suggestion: {e}")
        
        return None





