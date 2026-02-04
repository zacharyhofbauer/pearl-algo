"""
Deterministic graders for Pearl AI evaluation.

These graders evaluate response quality without requiring LLM calls,
enabling fast and reproducible regression testing.
"""

import re
from typing import Any, Callable, Dict, List, Optional, Set

from .types import GradeResult, GradeStatus, EvalCase, ResponseDebugInfo


# -----------------------------------------------------------------------------
# Routing Grader
# -----------------------------------------------------------------------------

def grade_routing(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade whether the query was routed correctly (QUICK vs DEEP).

    PASS if actual routing matches expected routing.
    SKIP if no expected routing specified.
    """
    if case.expected_routing is None:
        return GradeResult(
            grader_name="routing",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="No expected routing specified",
        )

    actual = debug_info.routing.lower()
    expected = case.expected_routing.lower()

    if actual == expected:
        return GradeResult(
            grader_name="routing",
            status=GradeStatus.PASS,
            score=1.0,
            reason=f"Correctly routed to {expected}",
            details={"actual": actual, "expected": expected},
        )
    else:
        return GradeResult(
            grader_name="routing",
            status=GradeStatus.FAIL,
            score=0.0,
            reason=f"Expected {expected} routing, got {actual}",
            details={"actual": actual, "expected": expected},
        )


# -----------------------------------------------------------------------------
# Tool Selection Grader
# -----------------------------------------------------------------------------

def grade_tool_selection(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade whether the correct tool was selected.

    PASS if:
    - Expected tool is None and no tools were called
    - Expected tool matches the called tool

    PARTIAL if tool was called but with wrong arguments.
    FAIL if wrong tool or unexpected tool usage.
    SKIP if tools are expected but model doesn't support tools (e.g., local LLM).
    """
    expected_tool = case.expected_tool
    tool_calls = debug_info.tool_calls

    # No tool expected
    if expected_tool is None:
        if not tool_calls:
            return GradeResult(
                grader_name="tool_selection",
                status=GradeStatus.PASS,
                score=1.0,
                reason="Correctly did not call any tools",
            )
        else:
            # Called tool when none expected - might be okay, mark as partial
            called_tools = [tc.get("name") for tc in tool_calls]
            return GradeResult(
                grader_name="tool_selection",
                status=GradeStatus.PARTIAL,
                score=0.5,
                reason=f"Called unexpected tool(s): {called_tools}",
                details={"called_tools": called_tools},
            )

    # Tool expected but none called
    if not tool_calls:
        # Check if we're using a model that doesn't support tools
        model = debug_info.model_used.lower()
        non_tool_models = ["llama", "ollama", "local", "template", "mock", "cache"]
        if any(m in model for m in non_tool_models):
            return GradeResult(
                grader_name="tool_selection",
                status=GradeStatus.SKIP,
                score=1.0,
                reason=f"Tool expected but model '{debug_info.model_used}' doesn't support tools",
                details={"expected_tool": expected_tool, "model": debug_info.model_used},
            )
        return GradeResult(
            grader_name="tool_selection",
            status=GradeStatus.FAIL,
            score=0.0,
            reason=f"Expected tool '{expected_tool}' but no tools were called",
            details={"expected_tool": expected_tool},
        )

    # Check if expected tool was called
    called_tools = [tc.get("name") for tc in tool_calls]
    if expected_tool in called_tools:
        # Correct tool called - check arguments if specified
        if case.expected_tool_args:
            for tc in tool_calls:
                if tc.get("name") == expected_tool:
                    actual_args = tc.get("input", {})
                    args_match = _check_tool_args(case.expected_tool_args, actual_args)
                    if args_match:
                        return GradeResult(
                            grader_name="tool_selection",
                            status=GradeStatus.PASS,
                            score=1.0,
                            reason=f"Correctly called '{expected_tool}' with expected arguments",
                            details={"expected_args": case.expected_tool_args, "actual_args": actual_args},
                        )
                    else:
                        return GradeResult(
                            grader_name="tool_selection",
                            status=GradeStatus.PARTIAL,
                            score=0.7,
                            reason=f"Called '{expected_tool}' but with different arguments",
                            details={"expected_args": case.expected_tool_args, "actual_args": actual_args},
                        )

        return GradeResult(
            grader_name="tool_selection",
            status=GradeStatus.PASS,
            score=1.0,
            reason=f"Correctly called tool '{expected_tool}'",
            details={"called_tools": called_tools},
        )

    # Wrong tool called
    return GradeResult(
        grader_name="tool_selection",
        status=GradeStatus.FAIL,
        score=0.0,
        reason=f"Expected '{expected_tool}', called {called_tools}",
        details={"expected_tool": expected_tool, "called_tools": called_tools},
    )


def _check_tool_args(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    """Check if actual args match expected (expected is subset check)."""
    for key, value in expected.items():
        if key not in actual:
            return False
        if actual[key] != value:
            return False
    return True


# -----------------------------------------------------------------------------
# Format Compliance Grader (Deep Responses)
# -----------------------------------------------------------------------------

def grade_format_compliance(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade whether deep responses follow the expected format:
    - Status line (1 sentence)
    - Observations (3-6 bullets)
    - Next steps (1-3 bullets)

    Only applies to DEEP responses.
    """
    if debug_info.routing.lower() != "deep":
        return GradeResult(
            grader_name="format_compliance",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="Format check only applies to deep responses",
        )

    checks = {
        "has_structure": False,
        "has_bullets": False,
        "reasonable_length": False,
    }

    # Check for bullet points (various formats)
    bullet_patterns = [r"^[\-\•\*]\s", r"^\d+\.\s"]
    has_bullets = any(
        re.search(pattern, response, re.MULTILINE)
        for pattern in bullet_patterns
    )
    checks["has_bullets"] = has_bullets

    # Check for reasonable structure (multiple paragraphs or sections)
    paragraphs = [p.strip() for p in response.split("\n\n") if p.strip()]
    checks["has_structure"] = len(paragraphs) >= 2 or has_bullets

    # Check reasonable length (not too short, not excessive)
    word_count = len(response.split())
    checks["reasonable_length"] = 20 <= word_count <= 500

    # Calculate score
    passed_checks = sum(checks.values())
    total_checks = len(checks)
    score = passed_checks / total_checks

    if score >= 0.9:
        status = GradeStatus.PASS
    elif score >= 0.5:
        status = GradeStatus.PARTIAL
    else:
        status = GradeStatus.FAIL

    failed = [k for k, v in checks.items() if not v]
    reason = f"Format checks: {passed_checks}/{total_checks} passed"
    if failed:
        reason += f" (missing: {', '.join(failed)})"

    return GradeResult(
        grader_name="format_compliance",
        status=status,
        score=score,
        reason=reason,
        details={"checks": checks, "word_count": word_count},
    )


# -----------------------------------------------------------------------------
# Length Compliance Grader (Narration)
# -----------------------------------------------------------------------------

def grade_length_compliance(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
    max_sentences: int = 2,
) -> GradeResult:
    """
    Grade whether narration responses are appropriately concise.

    Narrations should be 1-2 sentences max.
    Only applies to narration category.
    """
    from .types import EvalCategory

    if case.category != EvalCategory.NARRATION:
        return GradeResult(
            grader_name="length_compliance",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="Length check only applies to narration",
        )

    # Count sentences (split on sentence-ending punctuation).
    # Avoid counting decimal points in numbers (e.g., "$45.50") as sentence breaks.
    text = re.sub(r"(?<=\d)\.(?=\d)", "<DECIMAL>", response)
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = len(sentences)

    # Also check word count as backup
    word_count = len(response.split())

    # Thresholds for narration length
    # PASS: <= 2 sentences AND <= 80 words
    # PARTIAL: <= 3 sentences OR <= 100 words
    # FAIL: > 3 sentences AND > 100 words
    max_words_pass = 80
    max_words_partial = 100

    if sentence_count <= max_sentences and word_count <= max_words_pass:
        return GradeResult(
            grader_name="length_compliance",
            status=GradeStatus.PASS,
            score=1.0,
            reason=f"Appropriately concise ({sentence_count} sentences, {word_count} words)",
            details={"sentences": sentence_count, "words": word_count},
        )
    elif sentence_count <= max_sentences + 1 or word_count <= max_words_partial:
        return GradeResult(
            grader_name="length_compliance",
            status=GradeStatus.PARTIAL,
            score=0.7,
            reason=f"Slightly verbose ({sentence_count} sentences, {word_count} words)",
            details={"sentences": sentence_count, "words": word_count},
        )
    else:
        return GradeResult(
            grader_name="length_compliance",
            status=GradeStatus.FAIL,
            score=0.3,
            reason=f"Too verbose ({sentence_count} sentences, {word_count} words)",
            details={"sentences": sentence_count, "words": word_count},
        )


# -----------------------------------------------------------------------------
# Factual Numbers Grader
# -----------------------------------------------------------------------------

def grade_factual_numbers(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade whether numerical values in response match the input state.

    Extracts numbers from state and checks they appear correctly in response.
    Prevents hallucinated statistics.
    """
    state = case.input_state
    if not state:
        return GradeResult(
            grader_name="factual_numbers",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="No state provided to check against",
        )

    # Extract key numerical values from state
    expected_values = _extract_state_numbers(state)
    if not expected_values:
        return GradeResult(
            grader_name="factual_numbers",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="No numerical values in state to verify",
        )

    # Extract numbers from response
    response_numbers = _extract_response_numbers(response)

    # Check for contradictions (response has different value for same metric)
    contradictions = []
    matches = []

    for metric, expected in expected_values.items():
        # Check if response mentions this metric
        metric_mentioned = _metric_mentioned_in_response(metric, response)
        if metric_mentioned:
            # Check if the number matches
            if _number_matches_in_response(expected, response):
                matches.append(metric)
            else:
                # Check if a contradicting number appears
                contradictions.append({
                    "metric": metric,
                    "expected": expected,
                    "found_numbers": response_numbers,
                })

    if contradictions:
        return GradeResult(
            grader_name="factual_numbers",
            status=GradeStatus.FAIL,
            score=0.0,
            reason=f"Found {len(contradictions)} factual contradiction(s)",
            details={"contradictions": contradictions, "matches": matches},
        )

    if matches:
        return GradeResult(
            grader_name="factual_numbers",
            status=GradeStatus.PASS,
            score=1.0,
            reason=f"Verified {len(matches)} numerical value(s)",
            details={"matches": matches},
        )

    return GradeResult(
        grader_name="factual_numbers",
        status=GradeStatus.PASS,
        score=1.0,
        reason="No numerical claims to verify",
    )


def _extract_state_numbers(state: Dict[str, Any]) -> Dict[str, float]:
    """Extract numerical values from state that should be verifiable."""
    values = {}

    # Common trading state fields
    if "daily_pnl" in state:
        values["pnl"] = state["daily_pnl"]
    if "daily_trades" in state:
        values["trades"] = state["daily_trades"]
    if "daily_wins" in state:
        values["wins"] = state["daily_wins"]
    if "daily_losses" in state:
        values["losses"] = state["daily_losses"]
    if "active_trades_count" in state:
        values["positions"] = state["active_trades_count"]
    if "consecutive_wins" in state:
        values["consecutive_wins"] = state["consecutive_wins"]
    if "consecutive_losses" in state:
        values["consecutive_losses"] = state["consecutive_losses"]

    # Nested values
    if "risk_metrics" in state:
        rm = state["risk_metrics"]
        if "expectancy" in rm:
            values["expectancy"] = rm["expectancy"]
        if "max_drawdown" in rm:
            values["drawdown"] = rm["max_drawdown"]

    return values


def _extract_response_numbers(response: str) -> List[float]:
    """Extract all numbers from response text."""
    # Match integers, decimals, and currency amounts
    patterns = [
        r'\$[\d,]+\.?\d*',  # Currency
        r'\d+\.?\d*%',       # Percentages
        r'\d+\.\d+',         # Decimals
        r'\b\d+\b',          # Integers
    ]

    numbers = []
    for pattern in patterns:
        for match in re.findall(pattern, response):
            # Clean and convert
            clean = re.sub(r'[$,%]', '', match)
            try:
                numbers.append(float(clean))
            except ValueError:
                pass

    return numbers


def _metric_mentioned_in_response(metric: str, response: str) -> bool:
    """Check if a metric is specifically mentioned in the response."""
    import re

    # More precise patterns to avoid false positives
    # (e.g., "Profit & Loss" should not trigger "losses" metric)
    metric_patterns = {
        "pnl": [r"\bp&l\b", r"\bpnl\b", r"\bprofit\b", r"\bdaily p&l\b"],
        # Avoid false contradictions from generic phrases like "trading activity".
        # Only treat "trades" as mentioned when the response makes a numeric claim.
        "trades": [r"\b\d+\s*trades?\b"],
        "wins": [r"\b\d+\s*wins?\b", r"\bwinning\b", r"\bwon\b"],
        "losses": [r"\b\d+\s*loss(?:es)?\b", r"\blosing\b", r"\blost\s+\d+"],
        "positions": [r"\b\d+\s*positions?\b", r"\bactive positions?\b", r"\bopen positions?\b"],
        "consecutive_wins": [r"winning streak", r"wins? in a row", r"consecutive wins?"],
        "consecutive_losses": [r"losing streak", r"loss(?:es)? in a row", r"consecutive loss(?:es)?"],
        "expectancy": [r"\bexpectancy\b"],
        "drawdown": [r"\bdrawdown\b", r"\bdraw down\b"],
    }

    patterns = metric_patterns.get(metric, [rf"\b{metric}\b"])
    response_lower = response.lower()

    for pattern in patterns:
        if re.search(pattern, response_lower):
            return True
    return False


def _number_matches_in_response(expected: float, response: str) -> bool:
    """Check if expected number appears in response (with tolerance)."""
    response_numbers = _extract_response_numbers(response)
    tolerance = 0.01 if abs(expected) < 10 else abs(expected) * 0.01

    for num in response_numbers:
        if abs(num - abs(expected)) <= tolerance:
            return True
        # Also check negative
        if abs(num - expected) <= tolerance:
            return True

    return False


# -----------------------------------------------------------------------------
# Hallucination Pattern Grader
# -----------------------------------------------------------------------------

def grade_no_hallucination_patterns(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Check for common hallucination patterns.

    Detects phrases that often indicate fabricated information:
    - Claims about executing trades
    - Specific dates/times not in context
    - Made-up technical indicators
    - Confident claims without data backing
    """
    hallucination_patterns = [
        # Claims about executing actions
        (r"i (have |just )?(executed|placed|made|entered|exited) (a |the )?trade",
         "Claims to execute trades (Pearl only observes)"),
        (r"i('ve| have) (bought|sold|opened|closed)",
         "Claims to take trading actions"),

        # Specific unsupported claims
        (r"(yesterday|last week|last month|on \w+day).*\$\d+",
         "Specific historical claim without data"),
        (r"(RSI|MACD|bollinger|fibonacci|moving average) (is|shows|indicates) \d+",
         "Specific indicator value not in context"),

        # Overconfident predictions
        (r"(will|going to) (definitely|certainly|surely) (rise|fall|increase|decrease)",
         "Overconfident prediction"),
        (r"(guaranteed|100%|certain to)",
         "Absolute certainty claim"),
    ]

    found_patterns = []
    for pattern, description in hallucination_patterns:
        # Case-insensitive match (some patterns include uppercase tokens like RSI/MACD)
        if re.search(pattern, response, flags=re.IGNORECASE):
            found_patterns.append(description)

    # Check for failure modes specified in the case
    for failure_mode in case.failure_modes:
        if failure_mode.lower() in response.lower():
            found_patterns.append(f"Matched failure mode: {failure_mode}")

    if not found_patterns:
        return GradeResult(
            grader_name="no_hallucination",
            status=GradeStatus.PASS,
            score=1.0,
            reason="No hallucination patterns detected",
        )
    else:
        return GradeResult(
            grader_name="no_hallucination",
            status=GradeStatus.FAIL,
            score=0.0,
            reason=f"Detected {len(found_patterns)} hallucination pattern(s)",
            details={"patterns_found": found_patterns},
        )


# -----------------------------------------------------------------------------
# Voice Consistency Grader (Deterministic Checks)
# -----------------------------------------------------------------------------

def grade_voice_basic(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Basic deterministic voice checks.

    Checks for violations of the jarvis voice spec that can be detected
    without LLM grading:
    - No movie references
    - No excessive enthusiasm
    - Professional tone markers
    """
    violations = []

    # Movie reference check
    movie_refs = ["iron man", "tony stark", "jarvis", "avenger", "marvel", "stark tower"]
    response_lower = response.lower()
    for ref in movie_refs:
        if ref in response_lower:
            violations.append(f"Movie reference: '{ref}'")

    # Excessive enthusiasm check
    enthusiasm_patterns = [
        r"!!+",  # Multiple exclamation marks
        r"(amazing|awesome|fantastic|incredible|wonderful)!",
        r"(great news|exciting|wow)",
    ]
    for pattern in enthusiasm_patterns:
        if re.search(pattern, response_lower):
            violations.append(f"Excessive enthusiasm: matched '{pattern}'")

    # Emoji check (should not have emojis in trading context)
    emoji_pattern = r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]'
    if re.search(emoji_pattern, response):
        violations.append("Contains emoji (inappropriate for trading assistant)")

    if not violations:
        return GradeResult(
            grader_name="voice_basic",
            status=GradeStatus.PASS,
            score=1.0,
            reason="No voice violations detected",
        )
    else:
        return GradeResult(
            grader_name="voice_basic",
            status=GradeStatus.FAIL,
            score=0.0,
            reason=f"Found {len(violations)} voice violation(s)",
            details={"violations": violations},
        )


# -----------------------------------------------------------------------------
# Quality Criteria Grader
# -----------------------------------------------------------------------------

def grade_quality_criteria(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Check response against case-specific quality criteria.

    Uses simple keyword/phrase matching for criteria like:
    - "Must mention $150.50"
    - "Should include direction"
    """
    if not case.quality_criteria:
        return GradeResult(
            grader_name="quality_criteria",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="No quality criteria specified",
        )

    met_criteria = []
    unmet_criteria = []

    for criterion in case.quality_criteria:
        # Parse criterion type
        criterion_lower = criterion.lower()

        if criterion_lower.startswith("must "):
            # Required criterion
            requirement = criterion[5:].strip()
            if _criterion_met(requirement, response, case.input_state):
                met_criteria.append(criterion)
            else:
                unmet_criteria.append(criterion)
        elif criterion_lower.startswith("should "):
            # Soft criterion
            requirement = criterion[7:].strip()
            if _criterion_met(requirement, response, case.input_state):
                met_criteria.append(criterion)
            # Don't penalize for unmet "should" criteria
        else:
            # Treat as required
            if _criterion_met(criterion, response, case.input_state):
                met_criteria.append(criterion)
            else:
                unmet_criteria.append(criterion)

    if unmet_criteria:
        return GradeResult(
            grader_name="quality_criteria",
            status=GradeStatus.FAIL,
            score=len(met_criteria) / len(case.quality_criteria),
            reason=f"Unmet criteria: {unmet_criteria}",
            details={"met": met_criteria, "unmet": unmet_criteria},
        )

    return GradeResult(
        grader_name="quality_criteria",
        status=GradeStatus.PASS,
        score=1.0,
        reason=f"All {len(met_criteria)} criteria met",
        details={"met": met_criteria},
    )


def _criterion_met(criterion: str, response: str, state: Dict[str, Any]) -> bool:
    """Check if a single criterion is met."""
    criterion_lower = criterion.lower()
    response_lower = response.lower()

    # "mention X" or "include X"
    if "mention" in criterion_lower or "include" in criterion_lower:
        # Extract what should be mentioned
        match = re.search(r"(?:mention|include)\s+(.+)", criterion_lower)
        if match:
            target = match.group(1).strip()
            # Check for specific values (e.g., "$150.50")
            if target.startswith("$"):
                return target in response
            # Check for keywords
            return target in response_lower

    # Direct phrase check
    return criterion_lower in response_lower


# -----------------------------------------------------------------------------
# Grader Registry
# -----------------------------------------------------------------------------

class GraderRegistry:
    """
    Registry of all available graders.

    Allows selective grader execution based on case category and configuration.
    """

    # Default graders applied to all cases
    DEFAULT_GRADERS = [
        grade_no_hallucination_patterns,
        grade_voice_basic,
        grade_quality_criteria,
    ]

    # Category-specific graders
    CATEGORY_GRADERS = {
        "quick": [grade_routing, grade_factual_numbers],
        "deep": [grade_routing, grade_tool_selection, grade_format_compliance, grade_factual_numbers],
        "narration": [grade_length_compliance, grade_factual_numbers],
        "tool_selection": [grade_tool_selection],
        "coaching": [grade_factual_numbers],
        "classification": [grade_routing],
    }

    @classmethod
    def get_graders(cls, category: str) -> List[Callable]:
        """Get all applicable graders for a category."""
        graders = list(cls.DEFAULT_GRADERS)
        category_specific = cls.CATEGORY_GRADERS.get(category, [])

        # Add category-specific graders, avoiding duplicates
        for grader in category_specific:
            if grader not in graders:
                graders.append(grader)

        return graders

    @classmethod
    def run_all(
        cls,
        case: EvalCase,
        response: str,
        debug_info: ResponseDebugInfo,
    ) -> Dict[str, GradeResult]:
        """Run all applicable graders and return results."""
        graders = cls.get_graders(case.category.value)
        results = {}

        for grader in graders:
            try:
                result = grader(case, response, debug_info)
                results[result.grader_name] = result
            except Exception as e:
                results[grader.__name__] = GradeResult(
                    grader_name=grader.__name__,
                    status=GradeStatus.FAIL,
                    score=0.0,
                    reason=f"Grader error: {str(e)}",
                )

        return results
