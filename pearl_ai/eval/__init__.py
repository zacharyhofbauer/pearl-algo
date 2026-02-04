"""
Pearl AI Evaluation Framework

Provides automated evaluation of LLM responses for regression testing
and quality assurance.

Usage:
    from pearl_ai.eval import EvalRunner, load_dataset

    runner = EvalRunner(brain)
    report = await runner.run("datasets/golden_queries.json")
    print(report.summary())

With LLM-as-judge graders:
    from pearl_ai.eval import EvalRunner
    from pearl_ai.eval.graders_llm import run_llm_graders

    runner = EvalRunner(brain, enable_llm_graders=True)
    report = await runner.run("datasets/golden_queries.json")
"""

from .types import (
    EvalCase,
    EvalResult,
    EvalReport,
    GradeResult,
    ResponseDebugInfo,
    EvalCategory,
    GradeStatus,
)
from .graders import (
    grade_routing,
    grade_tool_selection,
    grade_format_compliance,
    grade_length_compliance,
    grade_factual_numbers,
    grade_no_hallucination_patterns,
    grade_voice_basic,
    grade_quality_criteria,
    GraderRegistry,
)
from .runner import EvalRunner, load_dataset, save_report

__all__ = [
    # Types
    "EvalCase",
    "EvalResult",
    "EvalReport",
    "GradeResult",
    "ResponseDebugInfo",
    "EvalCategory",
    "GradeStatus",
    # Deterministic Graders
    "grade_routing",
    "grade_tool_selection",
    "grade_format_compliance",
    "grade_length_compliance",
    "grade_factual_numbers",
    "grade_no_hallucination_patterns",
    "grade_voice_basic",
    "grade_quality_criteria",
    "GraderRegistry",
    # Runner
    "EvalRunner",
    "load_dataset",
    "save_report",
]
