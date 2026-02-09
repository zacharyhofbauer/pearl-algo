"""
LLM-as-Judge graders for Pearl AI evaluation.

These graders use a small, fast LLM to evaluate subjective quality dimensions
that cannot be assessed with deterministic rules.

Requires: Local Ollama or Claude API access.
"""

import asyncio
import logging
import re
from typing import Any, Dict, Optional

from .types import GradeResult, GradeStatus, EvalCase, ResponseDebugInfo

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# LLM Judge Base
# -----------------------------------------------------------------------------

class LLMJudge:
    """
    Base class for LLM-based grading.

    Uses local Ollama by default for cost efficiency.
    Falls back to deterministic grading if LLM unavailable.
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        host: str = "http://localhost:11434",
        timeout: float = 30.0,
    ):
        self.model = model
        self.host = host
        self.timeout = timeout
        self._available: Optional[bool] = None

    async def is_available(self) -> bool:
        """Check if the LLM backend is available."""
        if self._available is not None:
            return self._available

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.host}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    self._available = resp.status == 200
        except Exception:
            self._available = False

        return self._available

    async def judge(self, prompt: str) -> str:
        """Send prompt to LLM and get response."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # Low temp for consistent grading
                        "num_predict": 200,
                    },
                },
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"LLM request failed: {resp.status}")
                data = await resp.json()
                return data.get("response", "")

    def parse_verdict(self, response: str) -> tuple[GradeStatus, float, str]:
        """
        Parse LLM response into grade components.

        Expected format: PASS|FAIL|PARTIAL followed by reason.
        """
        response_upper = response.upper().strip()

        if response_upper.startswith("PASS"):
            return GradeStatus.PASS, 1.0, response.strip()
        elif response_upper.startswith("FAIL"):
            return GradeStatus.FAIL, 0.0, response.strip()
        elif response_upper.startswith("PARTIAL"):
            return GradeStatus.PARTIAL, 0.5, response.strip()
        else:
            # Try to find verdict in response
            if "PASS" in response_upper:
                return GradeStatus.PASS, 1.0, response.strip()
            elif "FAIL" in response_upper:
                return GradeStatus.FAIL, 0.0, response.strip()
            else:
                # Unclear - mark as partial
                return GradeStatus.PARTIAL, 0.5, f"Unclear verdict: {response.strip()}"


# Singleton judge instance
_judge: Optional[LLMJudge] = None


def get_judge() -> LLMJudge:
    """Get or create the LLM judge instance."""
    global _judge
    if _judge is None:
        _judge = LLMJudge()
    return _judge


# -----------------------------------------------------------------------------
# Voice Consistency Grader (LLM)
# -----------------------------------------------------------------------------

VOICE_CONSISTENCY_PROMPT = """You are evaluating a trading assistant's response for voice consistency.

The assistant should follow the "jarvis" voice specification:
- Crisp, composed, quietly confident
- Understated wit is allowed, never at expense of clarity
- No movie references (Iron Man, JARVIS, Tony Stark, Avengers)
- May address user as "sir" sparingly
- Prefers short paragraphs and bullet lists
- Never claims to execute trades (only observes and advises)
- States uncertainty plainly when data is unavailable

Response to evaluate:
"{response}"

Evaluate the voice consistency. Answer with PASS, PARTIAL, or FAIL followed by a brief reason (1 sentence).

Examples:
- PASS: Tone is crisp and professional with appropriate confidence.
- PARTIAL: Generally good but slightly too casual in places.
- FAIL: Overly enthusiastic tone with excessive punctuation.

Your verdict:"""


async def grade_voice_consistency_llm(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade voice consistency using LLM-as-judge.

    Evaluates whether the response follows the jarvis voice specification.
    Falls back to basic deterministic check if LLM unavailable.
    """
    judge = get_judge()

    if not await judge.is_available():
        # Fallback to deterministic grader
        from .graders import grade_voice_basic
        return grade_voice_basic(case, response, debug_info)

    try:
        prompt = VOICE_CONSISTENCY_PROMPT.format(response=response[:1000])
        llm_response = await judge.judge(prompt)
        status, score, reason = judge.parse_verdict(llm_response)

        return GradeResult(
            grader_name="voice_consistency_llm",
            status=status,
            score=score,
            reason=reason,
            details={"llm_response": llm_response},
        )
    except Exception as e:
        logger.warning(f"LLM voice grader failed: {e}, falling back to deterministic")
        from .graders import grade_voice_basic
        return grade_voice_basic(case, response, debug_info)


# -----------------------------------------------------------------------------
# Response Quality Grader (LLM)
# -----------------------------------------------------------------------------

RESPONSE_QUALITY_PROMPT = """You are evaluating a trading assistant's response quality.

User question: "{query}"

Trading context:
{context}

Assistant response:
"{response}"

Evaluate the response quality based on:
1. Relevance: Does it answer the user's question?
2. Accuracy: Does it correctly use the provided context data?
3. Helpfulness: Does it provide actionable information?
4. Clarity: Is it easy to understand?

Answer with PASS, PARTIAL, or FAIL followed by a brief reason (1-2 sentences).

Examples:
- PASS: Directly answers the question with accurate data from context.
- PARTIAL: Answers the question but misses some relevant context.
- FAIL: Does not address the user's question or contains incorrect information.

Your verdict:"""


async def grade_response_quality_llm(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade overall response quality using LLM-as-judge.

    Evaluates relevance, accuracy, helpfulness, and clarity.
    """
    judge = get_judge()

    if not await judge.is_available():
        return GradeResult(
            grader_name="response_quality_llm",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="LLM judge unavailable",
        )

    # Format context summary
    context_lines = []
    state = case.input_state
    if state:
        if "daily_pnl" in state:
            context_lines.append(f"- Daily P&L: ${state['daily_pnl']:.2f}")
        if "daily_trades" in state:
            context_lines.append(f"- Trades today: {state['daily_trades']}")
        if "daily_wins" in state:
            context_lines.append(f"- Wins: {state['daily_wins']}")
        if "active_trades_count" in state:
            context_lines.append(f"- Active positions: {state['active_trades_count']}")
        if "market_regime" in state:
            regime = state["market_regime"].get("regime", "unknown")
            context_lines.append(f"- Market regime: {regime}")

    context_str = "\n".join(context_lines) if context_lines else "No specific context provided."

    try:
        prompt = RESPONSE_QUALITY_PROMPT.format(
            query=case.input_query,
            context=context_str,
            response=response[:1000],
        )
        llm_response = await judge.judge(prompt)
        status, score, reason = judge.parse_verdict(llm_response)

        return GradeResult(
            grader_name="response_quality_llm",
            status=status,
            score=score,
            reason=reason,
            details={"llm_response": llm_response},
        )
    except Exception as e:
        logger.warning(f"LLM quality grader failed: {e}")
        return GradeResult(
            grader_name="response_quality_llm",
            status=GradeStatus.SKIP,
            score=1.0,
            reason=f"LLM judge error: {str(e)}",
        )


# -----------------------------------------------------------------------------
# Coaching Tone Grader (LLM)
# -----------------------------------------------------------------------------

COACHING_TONE_PROMPT = """You are evaluating a trading assistant's coaching tone.

The user experienced a trading loss or difficult situation:
Query: "{query}"
Context: {context}

Assistant response:
"{response}"

Evaluate if the response has appropriate coaching tone:
1. Constructive: Focuses on improvement, not blame
2. Supportive: Acknowledges difficulty without being dismissive
3. Actionable: Provides specific next steps or insights
4. Professional: Maintains composure, no panic or excessive emotion

Answer with PASS, PARTIAL, or FAIL followed by a brief reason.

Examples:
- PASS: Acknowledges the loss constructively and offers specific improvement areas.
- PARTIAL: Supportive but lacks actionable suggestions.
- FAIL: Blames the user or dismisses the concern.

Your verdict:"""


async def grade_coaching_tone_llm(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> GradeResult:
    """
    Grade coaching tone for loss/difficulty scenarios.

    Only applies to coaching-related cases.
    """
    from .types import EvalCategory

    # Only apply to coaching or loss-related cases
    is_coaching_case = (
        case.category == EvalCategory.COACHING or
        "coaching" in case.tags or
        "loss" in case.tags or
        any(kw in case.input_query.lower() for kw in ["losing", "lost", "fail", "mistake", "wrong"])
    )

    if not is_coaching_case:
        return GradeResult(
            grader_name="coaching_tone_llm",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="Not a coaching scenario",
        )

    judge = get_judge()

    if not await judge.is_available():
        return GradeResult(
            grader_name="coaching_tone_llm",
            status=GradeStatus.SKIP,
            score=1.0,
            reason="LLM judge unavailable",
        )

    # Format context
    context_str = "Loss scenario"
    if case.input_state:
        pnl = case.input_state.get("daily_pnl", 0)
        losses = case.input_state.get("consecutive_losses", 0)
        context_str = f"P&L: ${pnl:.2f}, Consecutive losses: {losses}"

    try:
        prompt = COACHING_TONE_PROMPT.format(
            query=case.input_query,
            context=context_str,
            response=response[:1000],
        )
        llm_response = await judge.judge(prompt)
        status, score, reason = judge.parse_verdict(llm_response)

        return GradeResult(
            grader_name="coaching_tone_llm",
            status=status,
            score=score,
            reason=reason,
            details={"llm_response": llm_response},
        )
    except Exception as e:
        logger.warning(f"LLM coaching grader failed: {e}")
        return GradeResult(
            grader_name="coaching_tone_llm",
            status=GradeStatus.SKIP,
            score=1.0,
            reason=f"LLM judge error: {str(e)}",
        )


# -----------------------------------------------------------------------------
# Registry Update
# -----------------------------------------------------------------------------

LLM_GRADERS = [
    grade_voice_consistency_llm,
    grade_response_quality_llm,
    grade_coaching_tone_llm,
]


async def run_llm_graders(
    case: EvalCase,
    response: str,
    debug_info: ResponseDebugInfo,
) -> Dict[str, GradeResult]:
    """Run all LLM-based graders concurrently."""
    tasks = [
        grader(case, response, debug_info)
        for grader in LLM_GRADERS
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    grader_results = {}
    for grader, result in zip(LLM_GRADERS, results):
        if isinstance(result, Exception):
            grader_results[grader.__name__] = GradeResult(
                grader_name=grader.__name__,
                status=GradeStatus.SKIP,
                score=1.0,
                reason=f"Grader error: {str(result)}",
            )
        else:
            grader_results[result.grader_name] = result

    return grader_results
