"""Backward compatibility — imports from tv_paper_eval_tracker."""
from pearlalgo.market_agent.tv_paper_eval_tracker import (
    TvPaperEvalConfig as MFFUEvalConfig,
    TvPaperEvalAttempt as MFFUEvalAttempt,
    TvPaperEvalTracker as MFFUEvaluationTracker,
)

__all__ = ["MFFUEvalConfig", "MFFUEvalAttempt", "MFFUEvaluationTracker"]
