"""
Pearl AI Metrics - Observability & Cost Tracking

Collects and aggregates metrics for Pearl AI operations:
- Token counting and cost calculation
- Latency percentiles
- Cache hit rates
- Error rates and fallback invocations
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
import json
import logging
from pathlib import Path

from .config import get_config
logger = logging.getLogger(__name__)

# Tool argument redaction (P2.3)
REDACTED_VALUE = "***redacted***"
MAX_TOOL_ARG_STRING = 200
SENSITIVE_ARG_KEYS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passphrase",
    "authorization",
)


def _is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(token in key_lower for token in SENSITIVE_ARG_KEYS)


def redact_tool_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Redact sensitive values from tool arguments."""
    def _redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (REDACTED_VALUE if _is_sensitive_key(k) else _redact(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_redact(v) for v in value]
        if isinstance(value, str):
            return value if len(value) <= MAX_TOOL_ARG_STRING else value[:MAX_TOOL_ARG_STRING] + "..."
        return value

    return _redact(arguments)


# Model pricing (USD per 1M tokens) - Updated 2024
MODEL_PRICING = {
    # Claude models
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 1.0, "output": 5.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    # Local models are free
    "llama3.1:8b": {"input": 0.0, "output": 0.0},
    "llama3.2:3b": {"input": 0.0, "output": 0.0},
}


@dataclass
class ToolCall:
    """Metrics for a single tool call (P2.3)."""
    name: str
    arguments: Dict[str, Any]
    success: bool
    latency_ms: float
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class LLMRequest:
    """Metrics for a single LLM request."""
    timestamp: datetime
    endpoint: str           # "chat", "narration", "coaching", "insight", "daily_review"
    model: str              # "llama3.1:8b", "claude-sonnet-4-20250514", "cache"
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cache_hit: bool = False
    success: bool = True
    error: Optional[str] = None
    fallback_used: bool = False
    tool_calls: Optional[List[ToolCall]] = None  # P2.3: Tool execution tracing

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        """Calculate cost based on model pricing."""
        if self.cache_hit or self.model == "cache":
            return 0.0

        pricing = MODEL_PRICING.get(self.model, {"input": 0.0, "output": 0.0})
        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "timestamp": self.timestamp.isoformat(),
            "endpoint": self.endpoint,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "cache_hit": self.cache_hit,
            "success": self.success,
            "error": self.error,
            "fallback_used": self.fallback_used,
        }
        # Add tool calls if present (P2.3)
        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return result


class MetricsCollector:
    """
    Collect and aggregate Pearl AI metrics.

    Provides:
    - Per-request recording
    - Time-windowed summaries
    - Percentile calculations
    - Cost tracking
    - Response source distribution (A2.2)
    - Persistence to disk
    """

    def __init__(
        self,
        max_history: Optional[int] = None,
        storage_path: Optional[Path] = None,
        daily_cost_limit: Optional[float] = None,
        persistence_frequency: Optional[int] = None,
        cost_warning_threshold: Optional[float] = None,
    ):
        """
        Initialize metrics collector.

        Args:
            max_history: Maximum number of requests to keep in memory
            storage_path: Optional path to persist metrics
            daily_cost_limit: Optional daily cost limit in USD (alerts if exceeded)
        """
        config = get_config()

        self.requests: List[LLMRequest] = []
        self.max_history = max_history if max_history is not None else config.metrics.MAX_HISTORY
        self.storage_path = storage_path
        self.daily_cost_limit = daily_cost_limit
        self.persistence_frequency = (
            persistence_frequency if persistence_frequency is not None else config.metrics.PERSISTENCE_FREQUENCY
        )
        self.cost_warning_threshold = (
            cost_warning_threshold if cost_warning_threshold is not None else config.metrics.COST_WARNING_THRESHOLD
        )

        # Counters for quick access
        self._total_requests = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._cache_hits = 0
        self._errors = 0
        self._fallbacks = 0
        self._dedupe_hits = 0
        self._dedupe_saved_tokens = 0
        self._dedupe_saved_cost = 0.0

        # Response source distribution tracking (A2.2)
        self._response_sources: Dict[str, int] = {
            "cache": 0,
            "local": 0,
            "claude": 0,
            "template": 0,
        }

        # Suggestion feedback tracking (I3.1)
        self._feedback_history: List[Dict[str, Any]] = []
        self._feedback_counts = {
            "accepted": 0,
            "dismissed": 0,
        }
        self._dismiss_reasons: Dict[str, int] = {
            "not_relevant": 0,
            "wrong_timing": 0,
            "too_risky": 0,
            "other": 0,
        }

        # Load persisted metrics if available
        if storage_path:
            self._load_metrics()

    def record(self, request: LLMRequest, source: Optional[str] = None) -> None:
        """
        Record an LLM request.

        Args:
            request: The LLMRequest to record
            source: Optional response source ("cache", "local", "claude", "template")
        """
        self.requests.append(request)

        # Update counters
        self._total_requests += 1
        self._total_tokens += request.total_tokens
        self._total_cost += request.cost_usd
        if request.cache_hit:
            self._cache_hits += 1
        if not request.success:
            self._errors += 1
        if request.fallback_used:
            self._fallbacks += 1

        # Track response source (A2.2)
        if source and source in self._response_sources:
            self._response_sources[source] += 1
        elif request.cache_hit:
            self._response_sources["cache"] += 1
        elif request.model in ["llama3.1:8b", "llama3.2:3b"]:
            self._response_sources["local"] += 1
        elif "claude" in request.model:
            self._response_sources["claude"] += 1
        elif request.model == "template":
            self._response_sources["template"] += 1

        # Trim history if needed
        if len(self.requests) > self.max_history:
            self.requests = self.requests[-self.max_history:]

        # Log if approaching cost limit
        if self.daily_cost_limit:
            today_cost = self.get_cost_today()
            if today_cost > self.daily_cost_limit * self.cost_warning_threshold:
                logger.warning(f"Daily cost ${today_cost:.2f} approaching limit ${self.daily_cost_limit:.2f}")

        # Periodic save
        if self._total_requests % self.persistence_frequency == 0 and self.storage_path:
            self._save_metrics()

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost

    def record_dedupe_hit(self, model: str, input_tokens: int, output_tokens: int) -> None:
        """Record a dedupe hit and estimated cost savings."""
        self._dedupe_hits += 1
        self._dedupe_saved_tokens += input_tokens + output_tokens
        self._dedupe_saved_cost += self._estimate_cost(model, input_tokens, output_tokens)

    def get_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get aggregated metrics summary for a time window.

        Args:
            hours: Number of hours to look back

        Returns:
            Summary dictionary with all metrics
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [r for r in self.requests if r.timestamp > cutoff]

        if not recent:
            return {
                "period_hours": hours,
                "total_requests": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "avg_latency_ms": 0.0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "p99_latency_ms": 0.0,
                "cache_hit_rate": 0.0,
                "error_rate": 0.0,
                "fallback_rate": 0.0,
                "by_endpoint": {},
                "by_model": {},
                "tool_stats": {"total_calls": 0, "overall": {}, "by_tool": {}},
                "dedupe": {
                    "period": "all_time",
                    "hits": self._dedupe_hits,
                    "saved_tokens": self._dedupe_saved_tokens,
                    "saved_cost_usd": round(self._dedupe_saved_cost, 4),
                },
            }

        # Calculate latency percentiles
        latencies = sorted([r.latency_ms for r in recent])

        def percentile(data: List[float], p: float) -> float:
            if not data:
                return 0.0
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = f + 1 if f < len(data) - 1 else f
            return data[f] + (k - f) * (data[c] - data[f])

        return {
            "period_hours": hours,
            "total_requests": len(recent),
            "total_tokens": sum(r.total_tokens for r in recent),
            "total_cost_usd": round(sum(r.cost_usd for r in recent), 4),
            "avg_latency_ms": round(sum(r.latency_ms for r in recent) / len(recent), 1),
            "p50_latency_ms": round(percentile(latencies, 50), 1),
            "p95_latency_ms": round(percentile(latencies, 95), 1),
            "p99_latency_ms": round(percentile(latencies, 99), 1),
            "cache_hit_rate": round(sum(1 for r in recent if r.cache_hit) / len(recent), 3),
            "error_rate": round(sum(1 for r in recent if not r.success) / len(recent), 3),
            "fallback_rate": round(sum(1 for r in recent if r.fallback_used) / len(recent), 3),
            "by_endpoint": self._group_by(recent, "endpoint"),
            "by_model": self._group_by(recent, "model"),
            "tool_stats": self._summarize_tool_calls(recent, percentile),
            "dedupe": {
                "period": "all_time",
                "hits": self._dedupe_hits,
                "saved_tokens": self._dedupe_saved_tokens,
                "saved_cost_usd": round(self._dedupe_saved_cost, 4),
            },
        }

    def _summarize_tool_calls(
        self,
        requests: List[LLMRequest],
        percentile_fn: Callable[[List[float], float], float],
    ) -> Dict[str, Any]:
        """Aggregate tool call counts, error rates, and latency."""
        tool_calls: List[ToolCall] = []
        for r in requests:
            if r.tool_calls:
                tool_calls.extend(r.tool_calls)

        if not tool_calls:
            return {"total_calls": 0, "overall": {}, "by_tool": {}}

        by_tool: Dict[str, Dict[str, Any]] = {}
        all_latencies: List[float] = []
        total_errors = 0

        for call in tool_calls:
            all_latencies.append(call.latency_ms)
            if not call.success:
                total_errors += 1

            bucket = by_tool.setdefault(call.name, {"count": 0, "errors": 0, "latencies": []})
            bucket["count"] += 1
            if not call.success:
                bucket["errors"] += 1
            bucket["latencies"].append(call.latency_ms)

        by_tool_summary = {}
        for name, data in by_tool.items():
            latencies = data["latencies"]
            count = data["count"]
            errors = data["errors"]
            by_tool_summary[name] = {
                "count": count,
                "error_rate": round(errors / count, 3) if count else 0.0,
                "avg_latency_ms": round(sum(latencies) / count, 1) if count else 0.0,
                "p95_latency_ms": round(percentile_fn(sorted(latencies), 95), 1) if count else 0.0,
            }

        total_calls = len(tool_calls)
        overall = {
            "count": total_calls,
            "error_rate": round(total_errors / total_calls, 3) if total_calls else 0.0,
            "avg_latency_ms": round(sum(all_latencies) / total_calls, 1) if total_calls else 0.0,
            "p95_latency_ms": round(percentile_fn(sorted(all_latencies), 95), 1) if total_calls else 0.0,
        }

        return {"total_calls": total_calls, "overall": overall, "by_tool": by_tool_summary}

    def _group_by(self, requests: List[LLMRequest], field: str) -> Dict[str, Dict[str, Any]]:
        """Group metrics by a field (endpoint or model)."""
        groups: Dict[str, List[LLMRequest]] = {}

        for r in requests:
            key = getattr(r, field)
            if key not in groups:
                groups[key] = []
            groups[key].append(r)

        result = {}
        for key, reqs in groups.items():
            result[key] = {
                "count": len(reqs),
                "tokens": sum(r.total_tokens for r in reqs),
                "cost_usd": round(sum(r.cost_usd for r in reqs), 4),
                "avg_latency_ms": round(sum(r.latency_ms for r in reqs) / len(reqs), 1),
                "error_rate": round(sum(1 for r in reqs if not r.success) / len(reqs), 3),
            }

        return result

    def get_cost_today(self) -> float:
        """Get total cost for today."""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_requests = [r for r in self.requests if r.timestamp >= today_start]
        return sum(r.cost_usd for r in today_requests)

    def get_cost_this_month(self) -> float:
        """Get total cost for this month."""
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_requests = [r for r in self.requests if r.timestamp >= month_start]
        return sum(r.cost_usd for r in month_requests)

    def get_recent_requests(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent requests for debugging."""
        return [r.to_dict() for r in self.requests[-limit:]]

    def get_error_summary(self, hours: int = 24) -> Dict[str, int]:
        """Get error counts by error type."""
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_errors = [r for r in self.requests if r.timestamp > cutoff and not r.success]

        error_counts: Dict[str, int] = {}
        for r in recent_errors:
            error_type = r.error or "unknown"
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

        return error_counts

    def get_response_source_distribution(self, hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Get response source distribution (A2.2).

        Args:
            hours: Optional time window. If None, returns all-time stats.

        Returns:
            Dictionary with counts and percentages for each source
        """
        if hours is None:
            # All-time distribution
            total = sum(self._response_sources.values())
            if total == 0:
                return {
                    "counts": self._response_sources.copy(),
                    "percentages": {k: 0.0 for k in self._response_sources},
                    "total": 0,
                    "period": "all_time",
                }

            return {
                "counts": self._response_sources.copy(),
                "percentages": {
                    k: round(v / total * 100, 1)
                    for k, v in self._response_sources.items()
                },
                "total": total,
                "period": "all_time",
            }

        # Time-windowed distribution
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [r for r in self.requests if r.timestamp > cutoff]

        source_counts = {"cache": 0, "local": 0, "claude": 0, "template": 0}
        for r in recent:
            if r.cache_hit:
                source_counts["cache"] += 1
            elif r.model in ["llama3.1:8b", "llama3.2:3b"]:
                source_counts["local"] += 1
            elif "claude" in r.model:
                source_counts["claude"] += 1
            else:
                source_counts["template"] += 1

        total = sum(source_counts.values())
        if total == 0:
            return {
                "counts": source_counts,
                "percentages": {k: 0.0 for k in source_counts},
                "total": 0,
                "period_hours": hours,
            }

        return {
            "counts": source_counts,
            "percentages": {
                k: round(v / total * 100, 1)
                for k, v in source_counts.items()
            },
            "total": total,
            "period_hours": hours,
        }

    def _save_metrics(self) -> None:
        """Save metrics to disk."""
        if not self.storage_path:
            return

        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            metrics_file = self.storage_path / "metrics.json"

            # Save last 24 hours of metrics
            cutoff = datetime.now() - timedelta(hours=24)
            recent = [r for r in self.requests if r.timestamp > cutoff]

            data = {
                "saved_at": datetime.now().isoformat(),
                "requests": [r.to_dict() for r in recent],
                "totals": {
                    "total_requests": self._total_requests,
                    "total_tokens": self._total_tokens,
                    "total_cost": round(self._total_cost, 4),
                    "cache_hits": self._cache_hits,
                    "errors": self._errors,
                    "fallbacks": self._fallbacks,
                }
            }
            data["dedupe"] = {
                "hits": self._dedupe_hits,
                "saved_tokens": self._dedupe_saved_tokens,
                "saved_cost": round(self._dedupe_saved_cost, 4),
            }

            metrics_file.write_text(json.dumps(data, indent=2))
            logger.debug(f"Saved {len(recent)} metrics records")

        except Exception as e:
            logger.error(f"Error saving metrics: {e}")

    def _load_metrics(self) -> None:
        """Load metrics from disk."""
        if not self.storage_path:
            return

        try:
            metrics_file = self.storage_path / "metrics.json"
            if not metrics_file.exists():
                return

            data = json.loads(metrics_file.read_text())

            # Restore recent requests
            for req_data in data.get("requests", []):
                try:
                    tool_calls_data = req_data.get("tool_calls") or []
                    tool_calls = [
                        ToolCall(
                            name=tc.get("name", "unknown"),
                            arguments=tc.get("arguments", {}),
                            success=tc.get("success", True),
                            latency_ms=tc.get("latency_ms", 0.0),
                            error=tc.get("error"),
                        )
                        for tc in tool_calls_data
                    ] if tool_calls_data else None
                    self.requests.append(LLMRequest(
                        timestamp=datetime.fromisoformat(req_data["timestamp"]),
                        endpoint=req_data["endpoint"],
                        model=req_data["model"],
                        input_tokens=req_data["input_tokens"],
                        output_tokens=req_data["output_tokens"],
                        latency_ms=req_data["latency_ms"],
                        cache_hit=req_data.get("cache_hit", False),
                        success=req_data.get("success", True),
                        error=req_data.get("error"),
                        fallback_used=req_data.get("fallback_used", False),
                        tool_calls=tool_calls,
                    ))
                except Exception:
                    pass  # Skip malformed entries

            # Restore counters
            totals = data.get("totals", {})
            self._total_requests = totals.get("total_requests", 0)
            self._total_tokens = totals.get("total_tokens", 0)
            self._total_cost = totals.get("total_cost", 0.0)
            self._cache_hits = totals.get("cache_hits", 0)
            self._errors = totals.get("errors", 0)
            self._fallbacks = totals.get("fallbacks", 0)

            dedupe = data.get("dedupe", {})
            self._dedupe_hits = dedupe.get("hits", 0)
            self._dedupe_saved_tokens = dedupe.get("saved_tokens", 0)
            self._dedupe_saved_cost = dedupe.get("saved_cost", 0.0)

            logger.info(f"Loaded {len(self.requests)} metrics records")

        except Exception as e:
            logger.error(f"Error loading metrics: {e}")

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        self.requests = []
        self._total_requests = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._cache_hits = 0
        self._errors = 0
        self._fallbacks = 0
        self._feedback_history = []
        self._feedback_counts = {"accepted": 0, "dismissed": 0}
        self._dismiss_reasons = {"not_relevant": 0, "wrong_timing": 0, "too_risky": 0, "other": 0}

    # ================================================================
    # SUGGESTION FEEDBACK TRACKING (I3.1)
    # ================================================================

    def record_feedback(self, feedback: Dict[str, Any]) -> None:
        """
        Record suggestion feedback (I3.1).

        Args:
            feedback: Dictionary containing:
                - suggestion_id: Unique ID of the suggestion
                - action: "accept" or "dismiss"
                - timestamp: When feedback was given
                - dismiss_reason: (optional) Why suggestion was dismissed
                - dismiss_comment: (optional) Additional comment
        """
        # Store in history (keep last 500)
        self._feedback_history.append(feedback)
        if len(self._feedback_history) > 500:
            self._feedback_history = self._feedback_history[-500:]

        # Update counts
        action = feedback.get("action", "")
        if action == "accept":
            self._feedback_counts["accepted"] += 1
        elif action == "dismiss":
            self._feedback_counts["dismissed"] += 1

            # Track dismiss reasons
            reason = feedback.get("dismiss_reason")
            if reason and reason in self._dismiss_reasons:
                self._dismiss_reasons[reason] += 1

        logger.debug(f"Recorded feedback: {action} for {feedback.get('suggestion_id', 'unknown')[:8]}")

    def get_feedback_stats(self, hours: Optional[int] = None) -> Dict[str, Any]:
        """
        Get suggestion feedback statistics (I3.1).

        Args:
            hours: Optional time window. If None, returns all-time stats.

        Returns:
            Dictionary with feedback statistics
        """
        if hours is None:
            # All-time stats
            total = self._feedback_counts["accepted"] + self._feedback_counts["dismissed"]
            acceptance_rate = (
                self._feedback_counts["accepted"] / total * 100
                if total > 0
                else 0.0
            )

            # Calculate dismiss reason percentages
            total_dismissed = self._feedback_counts["dismissed"]
            dismiss_reason_pct = {}
            if total_dismissed > 0:
                dismiss_reason_pct = {
                    reason: round(count / total_dismissed * 100, 1)
                    for reason, count in self._dismiss_reasons.items()
                }

            return {
                "total_accepted": self._feedback_counts["accepted"],
                "total_dismissed": self._feedback_counts["dismissed"],
                "total_feedback": total,
                "acceptance_rate": round(acceptance_rate, 1),
                "dismiss_reasons": self._dismiss_reasons.copy(),
                "dismiss_reasons_pct": dismiss_reason_pct,
                "period": "all_time",
            }

        # Time-windowed stats
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [
            f for f in self._feedback_history
            if datetime.fromisoformat(f.get("timestamp", "2020-01-01")) > cutoff
        ]

        accepted = sum(1 for f in recent if f.get("action") == "accept")
        dismissed = sum(1 for f in recent if f.get("action") == "dismiss")
        total = accepted + dismissed

        # Count dismiss reasons in window
        dismiss_reasons = {"not_relevant": 0, "wrong_timing": 0, "too_risky": 0, "other": 0}
        for f in recent:
            if f.get("action") == "dismiss":
                reason = f.get("dismiss_reason")
                if reason and reason in dismiss_reasons:
                    dismiss_reasons[reason] += 1

        acceptance_rate = accepted / total * 100 if total > 0 else 0.0

        dismiss_reason_pct = {}
        if dismissed > 0:
            dismiss_reason_pct = {
                reason: round(count / dismissed * 100, 1)
                for reason, count in dismiss_reasons.items()
            }

        return {
            "total_accepted": accepted,
            "total_dismissed": dismissed,
            "total_feedback": total,
            "acceptance_rate": round(acceptance_rate, 1),
            "dismiss_reasons": dismiss_reasons,
            "dismiss_reasons_pct": dismiss_reason_pct,
            "period_hours": hours,
        }

    def get_recent_feedback(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent feedback entries for debugging."""
        return self._feedback_history[-limit:]
