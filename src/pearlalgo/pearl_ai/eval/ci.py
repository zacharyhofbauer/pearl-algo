#!/usr/bin/env python3
"""
CI Integration for Pearl AI Evaluation

Provides entry points for continuous integration pipelines.

Usage:
    # Run full eval suite
    python -m pearlalgo.pearl_ai.eval.ci

    # Run only on changed prompt files (for pre-commit)
    python -m pearlalgo.pearl_ai.eval.ci --changed-only

    # Run with specific threshold
    python -m pearlalgo.pearl_ai.eval.ci --threshold 0.90

    # Run specific dataset
    python -m pearlalgo.pearl_ai.eval.ci --dataset golden_expanded.json
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pearlalgo.pearl_ai.eval.runner import EvalRunner, load_dataset, save_report
from pearlalgo.pearl_ai.eval.types import EvalReport

logger = logging.getLogger(__name__)

# Default paths
EVAL_DIR = Path(__file__).parent
DATASETS_DIR = EVAL_DIR / "datasets"
REPORTS_DIR = EVAL_DIR / "reports"
DEFAULT_DATASET = "golden_core.json"

# Files that trigger eval on change
PROMPT_FILES = [
    "pearl_ai/brain.py",
    "pearl_ai/narrator.py",
    "pearl_ai/tools.py",
    "pearl_ai/config.py",
    "pearl_ai/prompts/",
]


def get_changed_files() -> List[str]:
    """Get list of changed files from git."""
    try:
        # Get staged changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        staged = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Get unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        unstaged = result.stdout.strip().split("\n") if result.stdout.strip() else []

        return list(set(staged + unstaged))
    except subprocess.CalledProcessError:
        return []


def should_run_eval(changed_files: List[str]) -> bool:
    """Check if any prompt files were changed."""
    for changed in changed_files:
        for prompt_file in PROMPT_FILES:
            if changed.endswith(prompt_file) or prompt_file in changed:
                return True
    return False


def format_ci_output(report: EvalReport, threshold: float) -> str:
    """Format report for CI output."""
    lines = [
        "=" * 60,
        "Pearl AI Evaluation Report",
        "=" * 60,
        "",
        f"Run ID: {report.run_id}",
        f"Dataset: {report.dataset_path}",
        f"Duration: {report.duration_seconds:.1f}s",
        "",
        f"Results: {report.passed_cases}/{report.total_cases} passed ({report.pass_rate*100:.1f}%)",
        f"Threshold: {threshold*100:.0f}%",
        f"Status: {'PASS' if report.pass_rate >= threshold else 'FAIL'}",
        "",
    ]

    # Category breakdown
    lines.append("By Category:")
    for cat, results in report.by_category().items():
        passed = sum(1 for r in results if r.passed)
        rate = passed / len(results) * 100 if results else 0
        status = "✓" if rate >= threshold * 100 else "✗"
        lines.append(f"  {status} {cat}: {passed}/{len(results)} ({rate:.0f}%)")

    lines.append("")

    # Grader breakdown
    lines.append("By Grader:")
    for grader, stats in report.by_grader().items():
        total = stats["pass"] + stats["fail"] + stats["partial"]
        if total > 0:
            rate = stats["pass"] / total * 100
            status = "✓" if rate >= 80 else "✗"
            lines.append(f"  {status} {grader}: {stats['pass']}/{total} ({rate:.0f}%)")

    # Failed cases
    failures = report.failures()
    if failures:
        lines.append("")
        lines.append(f"Failed Cases ({len(failures)}):")
        for result in failures[:10]:
            lines.append(f"  - {result.case.id}: {result.case.input_query[:50]}...")
            for name, grade in result.grades.items():
                if grade.status.value == "fail":
                    lines.append(f"      {name}: {grade.reason[:60]}...")
        if len(failures) > 10:
            lines.append(f"  ... and {len(failures) - 10} more")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


async def run_ci_eval(
    dataset: str = DEFAULT_DATASET,
    threshold: float = 0.85,
    output_dir: Optional[Path] = None,
    mock: bool = False,
    verbose: bool = False,
    enable_llm_graders: bool = False,
) -> int:
    """
    Run evaluation for CI.

    Returns:
        Exit code (0 for pass, 1 for fail)
    """
    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Resolve dataset path
    dataset_path = DATASETS_DIR / dataset
    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        return 1

    # Setup output
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ci_run_{timestamp}.json"

    # Initialize runner
    if mock:
        runner = EvalRunner(mock_mode=True)
        logger.info("Running in mock mode")
    else:
        try:
            from pearlalgo.pearl_ai.brain import PearlBrain
            brain = PearlBrain(
                enable_local=True,
                enable_claude=bool(os.getenv("ANTHROPIC_API_KEY")),
            )
            runner = EvalRunner(brain=brain)
            logger.info("Running with real PearlBrain")
        except Exception as e:
            logger.warning(f"Failed to initialize PearlBrain: {e}")
            logger.info("Falling back to mock mode")
            runner = EvalRunner(mock_mode=True)

    # Run evaluation
    logger.info(f"Running eval on {dataset_path}")
    report = await runner.run(str(dataset_path), str(output_path))

    # Run LLM graders if enabled
    if enable_llm_graders and not mock:
        logger.info("Running LLM-as-judge graders...")
        try:
            from pearlalgo.pearl_ai.eval.graders_llm import run_llm_graders

            for result in report.results:
                llm_grades = await run_llm_graders(
                    result.case,
                    result.response,
                    result.debug_info,
                )
                result.grades.update(llm_grades)
        except Exception as e:
            logger.warning(f"LLM graders failed: {e}")

    # Output results
    print(format_ci_output(report, threshold))

    # Save updated report
    save_report(report, str(output_path))
    logger.info(f"Report saved to {output_path}")

    # Return exit code
    if report.pass_rate >= threshold:
        print(f"\n✓ PASSED: {report.pass_rate*100:.1f}% >= {threshold*100:.0f}%")
        return 0
    else:
        print(f"\n✗ FAILED: {report.pass_rate*100:.1f}% < {threshold*100:.0f}%")
        return 1


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Pearl AI Evaluation CI Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m pearlalgo.pearl_ai.eval.ci                      # Run default eval
  python -m pearlalgo.pearl_ai.eval.ci --threshold 0.90     # Require 90% pass rate
  python -m pearlalgo.pearl_ai.eval.ci --changed-only       # Only if prompt files changed
  python -m pearlalgo.pearl_ai.eval.ci --mock               # Use mock LLM
  python -m pearlalgo.pearl_ai.eval.ci --dataset golden_expanded.json
        """,
    )

    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Dataset file name (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Pass rate threshold (default: 0.85)",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only run if prompt files were changed",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with mock LLM (no API calls)",
    )
    parser.add_argument(
        "--llm-graders",
        action="store_true",
        help="Enable LLM-as-judge graders",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory for reports",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Check if we should skip
    if args.changed_only:
        changed = get_changed_files()
        if not should_run_eval(changed):
            print("No prompt files changed, skipping eval")
            sys.exit(0)
        print(f"Prompt files changed: {[f for f in changed if any(p in f for p in PROMPT_FILES)]}")

    # Run eval
    exit_code = asyncio.run(run_ci_eval(
        dataset=args.dataset,
        threshold=args.threshold,
        output_dir=args.output_dir,
        mock=args.mock,
        verbose=args.verbose,
        enable_llm_graders=args.llm_graders,
    ))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
