"""
Pearl AI Query Classifier - Improved routing with shadow comparison.

Provides an embedding-based classifier that runs alongside the keyword
baseline, logging disagreements for analysis without changing production
routing until the new classifier is validated.

The embedding approach uses pre-defined reference queries for each class
and cosine-similarity routing, which handles novel phrasing better than
keyword matching while remaining fully deterministic.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result from a query classifier."""
    label: str  # "quick" or "deep"
    confidence: float  # 0.0 to 1.0
    method: str  # "keyword", "embedding", "llm"


# ---------------------------------------------------------------------------
# Reference queries for embedding-based classification
# ---------------------------------------------------------------------------

QUICK_REFERENCE_QUERIES = [
    "what is my pnl",
    "current pnl",
    "status",
    "how many positions",
    "is the agent running",
    "win rate",
    "how am i doing",
    "open positions",
    "pnl today",
    "am i on a streak",
    "current price",
    "last trade",
    "how many trades",
    "agent status",
    "what time is it",
]

DEEP_REFERENCE_QUERIES = [
    "why am i losing",
    "explain my performance pattern",
    "analyze my trading strategy",
    "should i change my approach",
    "what patterns do you see",
    "compare my long vs short",
    "how do i perform in trending markets",
    "why was that signal rejected",
    "give me coaching advice",
    "review my week",
    "what am i doing wrong",
    "optimize my approach",
    "analyze my losing trades",
    "what should i improve",
    "compare my performance across regimes",
    "tell me about my streaks and what they mean",
    "backtest this idea",
    "similar trades to this setup",
]


# ---------------------------------------------------------------------------
# Simple TF-IDF-like embedding (no external deps required)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Simple whitespace + lowercase tokenizer."""
    return text.lower().split()


def _build_vocab(queries: List[str]) -> Dict[str, int]:
    """Build vocabulary from a list of queries."""
    vocab: Dict[str, int] = {}
    idx = 0
    for q in queries:
        for token in _tokenize(q):
            if token not in vocab:
                vocab[token] = idx
                idx += 1
    return vocab


def _to_vector(text: str, vocab: Dict[str, int]) -> List[float]:
    """Convert text to a bag-of-words vector."""
    vec = [0.0] * len(vocab)
    tokens = _tokenize(text)
    for token in tokens:
        if token in vocab:
            vec[vocab[token]] += 1.0
    return vec


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingClassifier:
    """
    Embedding-based query classifier using bag-of-words similarity.

    Compares the input query against reference queries for QUICK and DEEP
    classes, returning the class with higher average similarity.
    """

    def __init__(self) -> None:
        all_queries = QUICK_REFERENCE_QUERIES + DEEP_REFERENCE_QUERIES
        self._vocab = _build_vocab(all_queries + [""])  # ensure non-empty

        self._quick_vecs = [
            _to_vector(q, self._vocab) for q in QUICK_REFERENCE_QUERIES
        ]
        self._deep_vecs = [
            _to_vector(q, self._vocab) for q in DEEP_REFERENCE_QUERIES
        ]

    def classify(self, query: str) -> ClassificationResult:
        """Classify a query as QUICK or DEEP."""
        query_vec = _to_vector(query, self._vocab)

        # Average similarity to each class
        quick_sims = [_cosine_similarity(query_vec, v) for v in self._quick_vecs]
        deep_sims = [_cosine_similarity(query_vec, v) for v in self._deep_vecs]

        avg_quick = sum(quick_sims) / len(quick_sims) if quick_sims else 0.0
        avg_deep = sum(deep_sims) / len(deep_sims) if deep_sims else 0.0

        # Also consider max similarity (for short queries that match one ref well)
        max_quick = max(quick_sims) if quick_sims else 0.0
        max_deep = max(deep_sims) if deep_sims else 0.0

        # Weighted score: 60% avg, 40% max
        quick_score = 0.6 * avg_quick + 0.4 * max_quick
        deep_score = 0.6 * avg_deep + 0.4 * max_deep

        total = quick_score + deep_score
        if total == 0:
            return ClassificationResult(label="quick", confidence=0.5, method="embedding")

        if deep_score > quick_score:
            confidence = deep_score / total
            return ClassificationResult(label="deep", confidence=confidence, method="embedding")
        else:
            confidence = quick_score / total
            return ClassificationResult(label="quick", confidence=confidence, method="embedding")


# ---------------------------------------------------------------------------
# Shadow comparison logger
# ---------------------------------------------------------------------------

@dataclass
class ShadowComparisonLog:
    """Tracks disagreements between keyword and embedding classifiers."""

    agreements: int = 0
    disagreements: int = 0
    _recent_disagreements: List[Dict] = field(default_factory=list)
    _max_recent: int = 50

    def record(
        self,
        query: str,
        keyword_label: str,
        embedding_result: ClassificationResult,
    ) -> None:
        """Record a classification comparison."""
        if keyword_label == embedding_result.label:
            self.agreements += 1
        else:
            self.disagreements += 1
            entry = {
                "query": query[:100],
                "keyword": keyword_label,
                "embedding": embedding_result.label,
                "confidence": round(embedding_result.confidence, 3),
            }
            self._recent_disagreements.append(entry)
            if len(self._recent_disagreements) > self._max_recent:
                self._recent_disagreements = self._recent_disagreements[-self._max_recent:]

            logger.info(
                f"Classifier disagreement: keyword={keyword_label}, "
                f"embedding={embedding_result.label} "
                f"(conf={embedding_result.confidence:.2f}) "
                f"query='{query[:60]}'"
            )

    @property
    def agreement_rate(self) -> float:
        total = self.agreements + self.disagreements
        return self.agreements / total if total > 0 else 1.0

    def get_stats(self) -> Dict:
        """Get comparison statistics."""
        return {
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "agreement_rate": round(self.agreement_rate, 3),
            "recent_disagreements": list(self._recent_disagreements[-10:]),
        }


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_embedding_classifier: Optional[EmbeddingClassifier] = None
_shadow_log: Optional[ShadowComparisonLog] = None


def get_embedding_classifier() -> EmbeddingClassifier:
    """Get or create the global embedding classifier."""
    global _embedding_classifier
    if _embedding_classifier is None:
        _embedding_classifier = EmbeddingClassifier()
    return _embedding_classifier


def get_shadow_log() -> ShadowComparisonLog:
    """Get or create the global shadow comparison log."""
    global _shadow_log
    if _shadow_log is None:
        _shadow_log = ShadowComparisonLog()
    return _shadow_log
