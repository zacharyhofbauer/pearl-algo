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
from typing import Dict, List, Optional, Any
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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
        return {
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


class MetricsCollector:
    """
    Collect and aggregate Pearl AI metrics.

    Provides:
    - Per-request recording
    - Time-windowed summaries
    - Percentile calculations
    - Cost tracking
    - Persistence to disk
    """

    def __init__(
        self,
        max_history: int = 1000,
        storage_path: Optional[Path] = None,
        daily_cost_limit: Optional[float] = None,
    ):
        """
        Initialize metrics collector.

        Args:
            max_history: Maximum number of requests to keep in memory
            storage_path: Optional path to persist metrics
            daily_cost_limit: Optional daily cost limit in USD (alerts if exceeded)
        """
        self.requests: List[LLMRequest] = []
        self.max_history = max_history
        self.storage_path = storage_path
        self.daily_cost_limit = daily_cost_limit

        # Counters for quick access
        self._total_requests = 0
        self._total_tokens = 0
        self._total_cost = 0.0
        self._cache_hits = 0
        self._errors = 0
        self._fallbacks = 0

        # Load persisted metrics if available
        if storage_path:
            self._load_metrics()

    def record(self, request: LLMRequest) -> None:
        """
        Record an LLM request.

        Args:
            request: The LLMRequest to record
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

        # Trim history if needed
        if len(self.requests) > self.max_history:
            self.requests = self.requests[-self.max_history:]

        # Log if approaching cost limit
        if self.daily_cost_limit:
            today_cost = self.get_cost_today()
            if today_cost > self.daily_cost_limit * 0.8:
                logger.warning(f"Daily cost ${today_cost:.2f} approaching limit ${self.daily_cost_limit:.2f}")

        # Periodic save
        if self._total_requests % 100 == 0 and self.storage_path:
            self._save_metrics()

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
        }

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
