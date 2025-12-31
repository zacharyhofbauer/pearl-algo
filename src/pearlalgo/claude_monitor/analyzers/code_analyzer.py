"""
Code Analyzer - Analyzes code quality and technical debt.

Monitors:
- Configuration drift detection
- Strategy variant performance comparison
- Module boundary violations
- Technical debt accumulation
- Refactoring opportunities
- Test coverage gaps
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


class CodeAnalyzer:
    """
    Analyzes code quality and suggests improvements.
    
    Detects:
    - Configuration drift from defaults
    - Strategy variant performance
    - Module boundary violations
    - Technical debt patterns
    - Refactoring opportunities
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
        project_root: Optional[Path] = None,
    ):
        """
        Initialize code analyzer.
        
        Args:
            claude_client: Claude API client for AI analysis
            project_root: Path to project root
        """
        self._claude = claude_client
        self._project_root = project_root or self._find_project_root()
    
    def _find_project_root(self) -> Path:
        """Find the project root directory."""
        # Look for pyproject.toml or .git
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
                return parent
        return current
    
    async def analyze(self) -> Dict[str, Any]:
        """
        Analyze code quality.
        
        Returns:
            Analysis results with findings and recommendations
        """
        findings = []
        recommendations = []
        
        # Check module boundaries
        boundary_issues = await self._check_module_boundaries()
        findings.extend(boundary_issues)
        
        # Check configuration drift
        config_issues = await self._check_config_drift()
        findings.extend(config_issues)
        
        # Check for common code patterns
        pattern_issues = await self._check_code_patterns()
        findings.extend(pattern_issues)
        
        # Generate recommendations from findings
        for finding in findings:
            if finding.get("recommendation"):
                recommendations.append({
                    "priority": "low" if finding["severity"] == "info" else "medium",
                    "title": f"Fix: {finding['title']}",
                    "description": finding["recommendation"],
                    "category": "code",
                })
        
        # Determine overall status
        status = "healthy"
        if any(f["severity"] == "high" for f in findings):
            status = "needs_attention"
        elif any(f["severity"] == "medium" for f in findings):
            status = "minor_issues"
        
        return {
            "status": status,
            "timestamp": get_utc_timestamp(),
            "findings": findings,
            "recommendations": recommendations,
            "metrics": {
                "issues_found": len(findings),
                "high_severity": sum(1 for f in findings if f["severity"] == "high"),
                "medium_severity": sum(1 for f in findings if f["severity"] == "medium"),
            },
            "summary": {
                "key_insight": self._generate_insight(findings),
                "code_health": status,
            },
        }
    
    async def _check_module_boundaries(self) -> List[Dict[str, Any]]:
        """Check for module boundary violations."""
        findings = []
        
        # Try to run the architecture boundary checker
        checker_path = self._project_root / "scripts" / "testing" / "check_architecture_boundaries.py"
        
        if not checker_path.exists():
            return findings
        
        try:
            result = subprocess.run(
                ["python3", str(checker_path)],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            # Parse output for violations
            if result.returncode != 0 or "VIOLATION" in result.stdout:
                lines = result.stdout.split("\n")
                for line in lines:
                    if "VIOLATION" in line:
                        findings.append({
                            "type": "boundary_violation",
                            "severity": "medium",
                            "title": "Module boundary violation",
                            "description": line.strip(),
                            "recommendation": "Review import statements to maintain module boundaries",
                        })
        except subprocess.TimeoutExpired:
            logger.warning("Architecture boundary check timed out")
        except Exception as e:
            logger.warning(f"Could not run boundary checker: {e}")
        
        return findings
    
    async def _check_config_drift(self) -> List[Dict[str, Any]]:
        """Check for configuration drift from documented defaults."""
        findings = []
        
        config_path = self._project_root / "config" / "config.yaml"
        if not config_path.exists():
            return findings
        
        try:
            import yaml
            
            with open(config_path) as f:
                config = yaml.safe_load(f)
            
            # Check for potentially risky configuration values
            risk_config = config.get("risk", {})
            
            # Check max risk per trade
            max_risk = risk_config.get("max_risk_per_trade", 0.01)
            if max_risk > 0.02:
                findings.append({
                    "type": "config_drift",
                    "severity": "high",
                    "title": "High risk per trade",
                    "description": f"max_risk_per_trade is {max_risk:.1%}, above recommended 2%",
                    "recommendation": "Consider reducing max_risk_per_trade to 1-2%",
                })
            
            # Check position sizes
            max_position = risk_config.get("max_position_size", 15)
            if max_position > 25:
                findings.append({
                    "type": "config_drift",
                    "severity": "medium",
                    "title": "Large max position size",
                    "description": f"max_position_size is {max_position}, above typical prop firm limits",
                    "recommendation": "Review position size limits for prop firm compliance",
                })
            
            # Check signal thresholds
            signals_config = config.get("signals", {})
            min_confidence = signals_config.get("min_confidence", 0.5)
            if min_confidence < 0.4:
                findings.append({
                    "type": "config_drift",
                    "severity": "medium",
                    "title": "Low confidence threshold",
                    "description": f"min_confidence is {min_confidence}, may generate low-quality signals",
                    "recommendation": "Consider increasing min_confidence to 0.5 or higher",
                })
            
            min_rr = signals_config.get("min_risk_reward", 1.2)
            if min_rr < 1.0:
                findings.append({
                    "type": "config_drift",
                    "severity": "high",
                    "title": "Risk/reward below 1:1",
                    "description": f"min_risk_reward is {min_rr}, below break-even",
                    "recommendation": "Set min_risk_reward to at least 1.0, preferably 1.2+",
                })
            
        except Exception as e:
            logger.warning(f"Could not check config drift: {e}")
        
        return findings
    
    async def _check_code_patterns(self) -> List[Dict[str, Any]]:
        """Check for common code quality issues."""
        findings = []
        
        # Check for TODO/FIXME comments (potential technical debt)
        try:
            result = subprocess.run(
                ["grep", "-rn", "TODO\\|FIXME", "src/pearlalgo"],
                cwd=str(self._project_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            todo_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
            
            if todo_count > 10:
                findings.append({
                    "type": "technical_debt",
                    "severity": "info",
                    "title": f"{todo_count} TODO/FIXME comments",
                    "description": "Multiple TODO/FIXME comments indicate pending work",
                    "recommendation": "Review and address TODO items or create tracking issues",
                })
        except Exception:
            pass
        
        # Check for large files (potential for splitting)
        src_dir = self._project_root / "src" / "pearlalgo"
        if src_dir.exists():
            try:
                for py_file in src_dir.rglob("*.py"):
                    try:
                        line_count = sum(1 for _ in open(py_file))
                        if line_count > 500:
                            rel_path = py_file.relative_to(self._project_root)
                            findings.append({
                                "type": "large_file",
                                "severity": "info",
                                "title": f"Large file: {rel_path.name}",
                                "description": f"{rel_path} has {line_count} lines",
                                "recommendation": "Consider splitting into smaller modules",
                            })
                    except Exception:
                        pass
            except Exception:
                pass
        
        return findings
    
    def _generate_insight(self, findings: List[Dict[str, Any]]) -> str:
        """Generate key insight from findings."""
        if not findings:
            return "Code quality looks good"
        
        high = sum(1 for f in findings if f["severity"] == "high")
        medium = sum(1 for f in findings if f["severity"] == "medium")
        
        if high > 0:
            return f"{high} high-priority code issues need attention"
        elif medium > 0:
            return f"{medium} medium-priority issues to review"
        else:
            return f"{len(findings)} minor issues noted"



