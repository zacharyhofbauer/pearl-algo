"""
Type definitions for the Pearl AI evaluation framework.

These types define the structure of eval cases, results, and reports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class EvalCategory(str, Enum):
    """Categories of evaluation cases."""
    QUICK = "quick"
    DEEP = "deep"
    NARRATION = "narration"
    TOOL_SELECTION = "tool_selection"
    COACHING = "coaching"
    CLASSIFICATION = "classification"


class GradeStatus(str, Enum):
    """Status of a grade evaluation."""
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIP = "skip"  # Grader not applicable to this case


@dataclass
class GradeResult:
    """Result of a single grading dimension."""
    grader_name: str
    status: GradeStatus
    score: float  # 0.0 to 1.0
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == GradeStatus.PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grader": self.grader_name,
            "status": self.status.value,
            "score": self.score,
            "reason": self.reason,
            "details": self.details,
        }


@dataclass
class EvalCase:
    """
    A single evaluation test case.

    Attributes:
        id: Unique identifier for the case
        category: Type of evaluation (quick, deep, narration, etc.)
        input_query: The user query to test
        input_state: Trading state context for the query
        expected_routing: Expected QUICK or DEEP classification
        expected_tool: Expected tool to be called (if any)
        expected_tool_args: Expected arguments for tool call
        quality_criteria: Human-written criteria for quality
        reference_response: Optional known-good response for comparison
        failure_modes: Patterns that indicate failure
        event_type: For narration cases, the event type
        event_context: For narration cases, the event context
        tags: Optional tags for filtering
    """
    id: str
    category: EvalCategory
    input_query: str
    input_state: Dict[str, Any] = field(default_factory=dict)
    expected_routing: Optional[str] = None  # "quick" or "deep"
    expected_cache_hit: Optional[bool] = None
    expected_fallback_used: Optional[bool] = None
    expected_tool: Optional[str] = None
    expected_tool_args: Optional[Dict[str, Any]] = None
    max_sentences: Optional[int] = None  # Narration length constraint override
    quality_criteria: List[str] = field(default_factory=list)
    reference_response: Optional[str] = None
    failure_modes: List[str] = field(default_factory=list)
    event_type: Optional[str] = None  # For narration cases
    event_context: Optional[Dict[str, Any]] = None  # For narration cases
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvalCase":
        """Create EvalCase from dictionary."""
        category = data.get("category", "quick")
        if isinstance(category, str):
            category = EvalCategory(category)

        return cls(
            id=data["id"],
            category=category,
            input_query=data.get("input_query", ""),
            input_state=data.get("input_state", {}),
            expected_routing=data.get("expected_routing"),
            expected_cache_hit=data.get("expected_cache_hit"),
            expected_fallback_used=data.get("expected_fallback_used"),
            expected_tool=data.get("expected_tool"),
            expected_tool_args=data.get("expected_tool_args"),
            max_sentences=data.get("max_sentences"),
            quality_criteria=data.get("quality_criteria", []),
            reference_response=data.get("reference_response"),
            failure_modes=data.get("failure_modes", []),
            event_type=data.get("event_type"),
            event_context=data.get("event_context"),
            tags=data.get("tags", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "category": self.category.value,
            "input_query": self.input_query,
            "input_state": self.input_state,
            "expected_routing": self.expected_routing,
            "expected_cache_hit": self.expected_cache_hit,
            "expected_fallback_used": self.expected_fallback_used,
            "expected_tool": self.expected_tool,
            "expected_tool_args": self.expected_tool_args,
            "max_sentences": self.max_sentences,
            "quality_criteria": self.quality_criteria,
            "reference_response": self.reference_response,
            "failure_modes": self.failure_modes,
            "event_type": self.event_type,
            "event_context": self.event_context,
            "tags": self.tags,
        }


@dataclass
class ResponseDebugInfo:
    """
    Debug information captured during response generation.

    Used to understand what happened during the LLM call.
    """
    routing: str  # "quick" or "deep"
    model_used: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cache_hit: bool = False
    fallback_used: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routing": self.routing,
            "model_used": self.model_used,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
        }


@dataclass
class EvalResult:
    """
    Result of evaluating a single test case.

    Contains the case, response, debug info, and all grade results.
    """
    case: EvalCase
    response: str
    debug_info: ResponseDebugInfo
    grades: Dict[str, GradeResult] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def passed(self) -> bool:
        """Case passes if all applicable grades pass."""
        if self.error:
            return False
        applicable_grades = [g for g in self.grades.values() if g.status != GradeStatus.SKIP]
        return all(g.passed for g in applicable_grades)

    @property
    def score(self) -> float:
        """Average score across all applicable grades."""
        applicable_grades = [g for g in self.grades.values() if g.status != GradeStatus.SKIP]
        if not applicable_grades:
            return 1.0 if not self.error else 0.0
        return sum(g.score for g in applicable_grades) / len(applicable_grades)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case.id,
            "category": self.case.category.value,
            "query": self.case.input_query,
            "response": self.response,
            "debug_info": self.debug_info.to_dict(),
            "grades": {k: v.to_dict() for k, v in self.grades.items()},
            "passed": self.passed,
            "score": self.score,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class EvalReport:
    """
    Complete report from an evaluation run.

    Aggregates results across all test cases.
    """
    run_id: str
    dataset_path: str
    results: List[EvalResult]
    started_at: datetime
    completed_at: datetime
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_cases(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return self.passed_cases / self.total_cases

    @property
    def average_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    def by_category(self) -> Dict[str, List[EvalResult]]:
        """Group results by category."""
        grouped: Dict[str, List[EvalResult]] = {}
        for result in self.results:
            cat = result.case.category.value
            if cat not in grouped:
                grouped[cat] = []
            grouped[cat].append(result)
        return grouped

    def by_grader(self) -> Dict[str, Dict[str, int]]:
        """Aggregate pass/fail counts by grader."""
        grader_stats: Dict[str, Dict[str, int]] = {}
        for result in self.results:
            for grader_name, grade in result.grades.items():
                if grader_name not in grader_stats:
                    grader_stats[grader_name] = {"pass": 0, "fail": 0, "partial": 0, "skip": 0}
                grader_stats[grader_name][grade.status.value] += 1
        return grader_stats

    def failures(self) -> List[EvalResult]:
        """Get all failed cases."""
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Evaluation Report: {self.run_id}",
            f"Dataset: {self.dataset_path}",
            f"Duration: {self.duration_seconds:.1f}s",
            "",
            f"Results: {self.passed_cases}/{self.total_cases} passed ({self.pass_rate*100:.1f}%)",
            f"Average Score: {self.average_score:.2f}",
            "",
            "By Category:",
        ]

        for cat, results in self.by_category().items():
            passed = sum(1 for r in results if r.passed)
            lines.append(f"  {cat}: {passed}/{len(results)} passed")

        lines.append("")
        lines.append("By Grader:")
        for grader, stats in self.by_grader().items():
            total = stats["pass"] + stats["fail"] + stats["partial"]
            if total > 0:
                rate = stats["pass"] / total * 100
                lines.append(f"  {grader}: {stats['pass']}/{total} passed ({rate:.0f}%)")

        if self.failures():
            lines.append("")
            lines.append(f"Failed Cases ({len(self.failures())}):")
            for result in self.failures()[:5]:  # Show first 5
                lines.append(f"  - {result.case.id}: {result.case.input_query[:50]}...")
            if len(self.failures()) > 5:
                lines.append(f"  ... and {len(self.failures()) - 5} more")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_path": self.dataset_path,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "pass_rate": self.pass_rate,
            "average_score": self.average_score,
            "config": self.config,
            "by_category": {
                cat: {"total": len(results), "passed": sum(1 for r in results if r.passed)}
                for cat, results in self.by_category().items()
            },
            "by_grader": self.by_grader(),
            "results": [r.to_dict() for r in self.results],
        }
