"""
Pearl AI Output Validator - Post-LLM response safety checks.

Runs lightweight checks on every LLM response before it is cached or
returned to the user. Checks are additive (never silently strip content)
and violations are logged for observability.

Checks:
- PII patterns (SSN, account numbers, credit cards)
- Action claims ("I executed", "I placed a trade")
- Executable code blocks in responses
- Response length bounds
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationViolation:
    """A single output validation violation."""
    check: str
    severity: str  # "warning" or "error"
    detail: str


@dataclass
class ValidationResult:
    """Result of validating an LLM output."""
    valid: bool
    violations: List[ValidationViolation] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == "error" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return any(v.severity == "warning" for v in self.violations)

    def summary(self) -> str:
        if self.valid:
            return "OK"
        parts = [f"{v.check}: {v.detail}" for v in self.violations]
        return "; ".join(parts)


class OutputValidator:
    """
    Validates LLM output before it reaches the user.

    All checks are opt-in via constructor flags. Violations are logged
    but the response is still returned (transparency over silent correction).
    """

    # ----------------------------------------------------------------
    # PII patterns
    # ----------------------------------------------------------------
    _PII_PATTERNS = [
        # US Social Security Number
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "SSN-like pattern"),
        # Credit card (Visa/MC/Amex loose)
        (re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{3,4}\b"), "credit-card-like pattern"),
        # Email address (may appear via RAG context leak)
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "email address"),
        # US phone number
        (re.compile(r"\b(?:\+1[\s-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "phone-number-like pattern"),
        # Generic account / routing number pattern
        (re.compile(r"\baccount\s*#?\s*:?\s*\d{6,}\b", re.IGNORECASE), "account-number-like pattern"),
    ]

    # ----------------------------------------------------------------
    # Action claim patterns (Pearl must never claim to execute trades)
    # ----------------------------------------------------------------
    _ACTION_CLAIMS = [
        re.compile(r"\bi\s+(?:have\s+|just\s+)?(?:executed|placed|made|entered|exited)\s+(?:a\s+|the\s+)?(?:trade|order|position)", re.IGNORECASE),
        re.compile(r"\bi(?:'ve|\s+have)\s+(?:bought|sold|opened|closed)", re.IGNORECASE),
        re.compile(r"\bi\s+(?:will|am going to)\s+(?:execute|place|enter|exit)\s+(?:a\s+|the\s+)?(?:trade|order)", re.IGNORECASE),
    ]

    # ----------------------------------------------------------------
    # Executable code block patterns
    # ----------------------------------------------------------------
    _EXECUTABLE_BLOCKS = [
        re.compile(r"```(?:python|javascript|bash|sh|shell|sql|exec)\b", re.IGNORECASE),
        re.compile(r"<script\b", re.IGNORECASE),
        re.compile(r"eval\s*\(", re.IGNORECASE),
    ]

    def __init__(
        self,
        check_pii: bool = True,
        check_action_claims: bool = True,
        check_executable: bool = True,
        check_length: bool = True,
        max_response_length: int = 5000,
        min_response_length: int = 1,
    ):
        self.check_pii = check_pii
        self.check_action_claims = check_action_claims
        self.check_executable = check_executable
        self.check_length = check_length
        self.max_response_length = max_response_length
        self.min_response_length = min_response_length

    def validate(self, response: str, endpoint: str = "chat") -> ValidationResult:
        """
        Validate an LLM response.

        Args:
            response: The generated response text.
            endpoint: Which endpoint generated this (for logging context).

        Returns:
            ValidationResult with any violations.
        """
        violations: List[ValidationViolation] = []

        if self.check_pii:
            violations.extend(self._check_pii(response))

        if self.check_action_claims:
            violations.extend(self._check_action_claims(response))

        if self.check_executable:
            violations.extend(self._check_executable(response))

        if self.check_length:
            violations.extend(self._check_length(response))

        result = ValidationResult(
            valid=not any(v.severity == "error" for v in violations),
            violations=violations,
        )

        # Log violations
        if violations:
            for v in violations:
                if v.severity == "error":
                    logger.warning(
                        f"Output validation error [{endpoint}]: {v.check} - {v.detail}"
                    )
                else:
                    logger.info(
                        f"Output validation warning [{endpoint}]: {v.check} - {v.detail}"
                    )

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_pii(self, response: str) -> List[ValidationViolation]:
        """Check for PII patterns in the response."""
        violations = []
        for pattern, description in self._PII_PATTERNS:
            if pattern.search(response):
                violations.append(ValidationViolation(
                    check="pii_detected",
                    severity="error",
                    detail=f"Response contains {description}",
                ))
        return violations

    def _check_action_claims(self, response: str) -> List[ValidationViolation]:
        """Check for action claims (Pearl claiming to execute trades)."""
        violations = []
        for pattern in self._ACTION_CLAIMS:
            match = pattern.search(response)
            if match:
                violations.append(ValidationViolation(
                    check="action_claim",
                    severity="warning",
                    detail=f"Response contains action claim: '{match.group()[:60]}'",
                ))
        return violations

    def _check_executable(self, response: str) -> List[ValidationViolation]:
        """Check for executable code blocks."""
        violations = []
        for pattern in self._EXECUTABLE_BLOCKS:
            if pattern.search(response):
                violations.append(ValidationViolation(
                    check="executable_block",
                    severity="warning",
                    detail=f"Response contains executable code pattern",
                ))
        return violations

    def _check_length(self, response: str) -> List[ValidationViolation]:
        """Check response length bounds."""
        violations = []
        length = len(response)

        if length < self.min_response_length:
            violations.append(ValidationViolation(
                check="length_too_short",
                severity="warning",
                detail=f"Response too short ({length} chars < {self.min_response_length})",
            ))

        if length > self.max_response_length:
            violations.append(ValidationViolation(
                check="length_too_long",
                severity="warning",
                detail=f"Response too long ({length} chars > {self.max_response_length})",
            ))

        return violations


# Module-level singleton
_validator: Optional[OutputValidator] = None


def get_output_validator() -> OutputValidator:
    """Get or create the global output validator."""
    global _validator
    if _validator is None:
        _validator = OutputValidator()
    return _validator
