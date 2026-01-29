"""
Filter Analytics - Analyze filter effectiveness and generate recommendations.

This module provides comprehensive analytics for trading filters, including:
- Effectiveness scoring based on hypothetical outcomes
- Time-based performance analysis
- Auto-adjustment recommendations (with human approval)
- Learning reports and insights
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum

from pearlalgo.learning.opportunity_tracker import (
    OpportunityTracker,
    OpportunityDecision,
    get_opportunity_tracker,
)
from pearlalgo.utils.logger import logger


class AdjustmentType(Enum):
    """Types of filter adjustments."""
    KEEP = "keep"                    # Keep filter as-is
    RELAX = "relax"                  # Make filter less strict
    TIGHTEN = "tighten"              # Make filter more strict
    DISABLE = "disable"              # Disable filter entirely
    ENABLE = "enable"                # Enable disabled filter
    MODIFY_THRESHOLD = "modify_threshold"  # Change threshold value


@dataclass
class FilterAdjustmentRecommendation:
    """A recommended adjustment to a filter."""
    filter_name: str
    adjustment_type: AdjustmentType
    
    # Current vs recommended settings
    current_setting: Any
    recommended_setting: Any
    
    # Evidence
    confidence: float  # 0-1 confidence in recommendation
    evidence_count: int  # Number of data points
    
    # Impact estimates
    estimated_additional_wins: float
    estimated_additional_losses: float
    estimated_net_pnl_change: float
    
    # Reasoning
    reasoning: str
    
    # Status
    requires_approval: bool = True
    approved: bool = False
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_name": self.filter_name,
            "adjustment_type": self.adjustment_type.value,
            "current_setting": self.current_setting,
            "recommended_setting": self.recommended_setting,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "estimated_additional_wins": self.estimated_additional_wins,
            "estimated_additional_losses": self.estimated_additional_losses,
            "estimated_net_pnl_change": self.estimated_net_pnl_change,
            "reasoning": self.reasoning,
            "requires_approval": self.requires_approval,
            "approved": self.approved,
        }


@dataclass
class FilterPerformanceReport:
    """Comprehensive performance report for a filter."""
    filter_name: str
    period_days: int
    generated_at: datetime
    
    # Overall metrics
    total_evaluations: int
    total_blocked: int
    block_rate: float
    
    # Hypothetical outcomes
    blocked_would_have_won: int
    blocked_would_have_lost: int
    blocked_hypothetical_win_rate: float
    
    # P&L impact
    saved_pnl: float  # Sum of losses prevented
    missed_pnl: float  # Sum of wins missed
    net_pnl_impact: float
    
    # Effectiveness score (0-1, higher is better)
    effectiveness_score: float
    
    # Time-based breakdown
    hourly_performance: dict[int, dict[str, float]] = field(default_factory=dict)
    
    # Regime-based breakdown
    regime_performance: dict[str, dict[str, float]] = field(default_factory=dict)
    
    # Recommendations
    recommendations: list[FilterAdjustmentRecommendation] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "filter_name": self.filter_name,
            "period_days": self.period_days,
            "generated_at": self.generated_at.isoformat(),
            "total_evaluations": self.total_evaluations,
            "total_blocked": self.total_blocked,
            "block_rate": self.block_rate,
            "blocked_would_have_won": self.blocked_would_have_won,
            "blocked_would_have_lost": self.blocked_would_have_lost,
            "blocked_hypothetical_win_rate": self.blocked_hypothetical_win_rate,
            "saved_pnl": self.saved_pnl,
            "missed_pnl": self.missed_pnl,
            "net_pnl_impact": self.net_pnl_impact,
            "effectiveness_score": self.effectiveness_score,
            "hourly_performance": self.hourly_performance,
            "regime_performance": self.regime_performance,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


class FilterAnalytics:
    """
    Analyzes filter effectiveness and generates recommendations.
    
    Features:
    - Calculate effectiveness metrics for each filter
    - Time-based performance analysis (by hour, by regime)
    - Generate auto-adjustment recommendations
    - Track recommendation history
    
    Usage:
        analytics = FilterAnalytics()
        
        # Get report for a specific filter
        report = analytics.analyze_filter("session_filter", period_days=30)
        print(f"Effectiveness: {report.effectiveness_score:.2f}")
        
        # Get all recommendations
        recs = analytics.get_recommendations(min_confidence=0.7)
        for rec in recs:
            print(f"{rec.filter_name}: {rec.adjustment_type.value}")
    """
    
    def __init__(
        self,
        tracker: Optional[OpportunityTracker] = None,
        min_samples_for_recommendation: int = 20,
        auto_adjust_enabled: bool = False,
    ):
        """
        Initialize filter analytics.
        
        Args:
            tracker: OpportunityTracker instance
            min_samples_for_recommendation: Minimum samples needed for recommendations
            auto_adjust_enabled: Whether to allow auto-adjustments (with approval)
        """
        self._tracker = tracker or get_opportunity_tracker()
        self._min_samples = min_samples_for_recommendation
        self._auto_adjust_enabled = auto_adjust_enabled
        
        # Pending recommendations
        self._pending_recommendations: dict[str, FilterAdjustmentRecommendation] = {}
        
        logger.info(f"FilterAnalytics initialized (min_samples={min_samples_for_recommendation})")
    
    def analyze_filter(
        self,
        filter_name: str,
        period_days: int = 30,
    ) -> FilterPerformanceReport:
        """
        Generate a comprehensive performance report for a filter.
        
        Args:
            filter_name: Name of the filter to analyze
            period_days: Period to analyze
            
        Returns:
            FilterPerformanceReport with all metrics
        """
        # Get basic effectiveness from tracker
        effectiveness = self._tracker.get_filter_effectiveness(filter_name, period_days)
        
        # Calculate derived metrics
        total_blocked = effectiveness["signals_blocked"]
        would_have_won = effectiveness["would_have_won"]
        would_have_lost = effectiveness["would_have_lost"]
        
        total_outcomes = would_have_won + would_have_lost
        hypothetical_win_rate = would_have_won / total_outcomes if total_outcomes > 0 else 0.0
        
        # Get time-based breakdown
        hourly_performance = self._get_hourly_performance(filter_name, period_days)
        regime_performance = self._get_regime_performance(filter_name, period_days)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            filter_name=filter_name,
            effectiveness=effectiveness,
            hourly_performance=hourly_performance,
            regime_performance=regime_performance,
        )
        
        return FilterPerformanceReport(
            filter_name=filter_name,
            period_days=period_days,
            generated_at=datetime.now(timezone.utc),
            total_evaluations=total_blocked,  # We only have blocked data
            total_blocked=total_blocked,
            block_rate=1.0,  # All data is blocked signals
            blocked_would_have_won=would_have_won,
            blocked_would_have_lost=would_have_lost,
            blocked_hypothetical_win_rate=hypothetical_win_rate,
            saved_pnl=effectiveness["saved_pnl"],
            missed_pnl=effectiveness["missed_pnl"],
            net_pnl_impact=effectiveness["net_pnl"],
            effectiveness_score=effectiveness["effectiveness_score"],
            hourly_performance=hourly_performance,
            regime_performance=regime_performance,
            recommendations=recommendations,
        )
    
    def _get_hourly_performance(
        self,
        filter_name: str,
        period_days: int,
    ) -> dict[int, dict[str, float]]:
        """Get filter performance broken down by hour."""
        # This would query the database for hourly breakdown
        # Stub implementation
        return {}
    
    def _get_regime_performance(
        self,
        filter_name: str,
        period_days: int,
    ) -> dict[str, dict[str, float]]:
        """Get filter performance broken down by market regime."""
        # This would query the database for regime breakdown
        # Stub implementation
        return {}
    
    def _generate_recommendations(
        self,
        filter_name: str,
        effectiveness: dict[str, Any],
        hourly_performance: dict[int, dict[str, float]],
        regime_performance: dict[str, dict[str, float]],
    ) -> list[FilterAdjustmentRecommendation]:
        """Generate recommendations based on analysis."""
        recommendations = []
        
        total_blocked = effectiveness["signals_blocked"]
        hypothetical_win_rate = effectiveness["hypothetical_win_rate"]
        net_pnl = effectiveness["net_pnl"]
        effectiveness_score = effectiveness["effectiveness_score"]
        
        # Skip if insufficient data
        if total_blocked < self._min_samples:
            return recommendations
        
        # Recommendation 1: Relax filter if hypothetical win rate is high
        if hypothetical_win_rate > 0.55:
            confidence = min(0.9, hypothetical_win_rate - 0.05)  # Higher WR = more confidence
            
            # Estimate impact of relaxing
            estimated_additional_wins = total_blocked * hypothetical_win_rate * 0.5  # Assume 50% would pass
            estimated_additional_losses = total_blocked * (1 - hypothetical_win_rate) * 0.5
            estimated_net_pnl = effectiveness["missed_pnl"] * 0.5 - effectiveness["saved_pnl"] * 0.5 * (1 - hypothetical_win_rate)
            
            recommendations.append(FilterAdjustmentRecommendation(
                filter_name=filter_name,
                adjustment_type=AdjustmentType.RELAX,
                current_setting="strict",
                recommended_setting="relaxed",
                confidence=confidence,
                evidence_count=total_blocked,
                estimated_additional_wins=estimated_additional_wins,
                estimated_additional_losses=estimated_additional_losses,
                estimated_net_pnl_change=estimated_net_pnl,
                reasoning=f"Hypothetical win rate of {hypothetical_win_rate:.0%} suggests filter may be too strict. "
                         f"Blocked signals would have generated ${effectiveness['missed_pnl']:.0f} in P&L.",
                requires_approval=True,
            ))
        
        # Recommendation 2: Tighten filter if effectiveness is low
        elif effectiveness_score < 0.3 and net_pnl < 0:
            confidence = 0.6  # Moderate confidence
            
            recommendations.append(FilterAdjustmentRecommendation(
                filter_name=filter_name,
                adjustment_type=AdjustmentType.TIGHTEN,
                current_setting="current",
                recommended_setting="stricter",
                confidence=confidence,
                evidence_count=total_blocked,
                estimated_additional_wins=0,
                estimated_additional_losses=total_blocked * 0.1,  # Estimate
                estimated_net_pnl_change=abs(net_pnl) * 0.3,  # Estimate
                reasoning=f"Filter effectiveness score ({effectiveness_score:.2f}) is low with negative net P&L impact. "
                         f"Consider tightening threshold to improve signal quality.",
                requires_approval=True,
            ))
        
        # Recommendation 3: Keep filter if effective
        elif effectiveness_score > 0.5:
            recommendations.append(FilterAdjustmentRecommendation(
                filter_name=filter_name,
                adjustment_type=AdjustmentType.KEEP,
                current_setting="current",
                recommended_setting="current",
                confidence=0.8,
                evidence_count=total_blocked,
                estimated_additional_wins=0,
                estimated_additional_losses=0,
                estimated_net_pnl_change=0,
                reasoning=f"Filter is effective (score: {effectiveness_score:.2f}) with positive net P&L impact of ${net_pnl:.0f}. "
                         f"Recommend keeping current settings.",
                requires_approval=False,
            ))
        
        # Store pending recommendations
        for rec in recommendations:
            if rec.requires_approval and rec.adjustment_type != AdjustmentType.KEEP:
                self._pending_recommendations[filter_name] = rec
        
        return recommendations
    
    def get_all_filter_reports(
        self,
        period_days: int = 30,
    ) -> list[FilterPerformanceReport]:
        """Generate reports for all filters."""
        all_effectiveness = self._tracker.get_all_filter_effectiveness(period_days)
        
        reports = []
        for eff in all_effectiveness:
            report = self.analyze_filter(eff["filter_name"], period_days)
            reports.append(report)
        
        return reports
    
    def get_recommendations(
        self,
        min_confidence: float = 0.5,
        exclude_keep: bool = True,
    ) -> list[FilterAdjustmentRecommendation]:
        """
        Get all pending recommendations.
        
        Args:
            min_confidence: Minimum confidence threshold
            exclude_keep: Whether to exclude "keep" recommendations
            
        Returns:
            List of recommendations
        """
        recs = list(self._pending_recommendations.values())
        
        if exclude_keep:
            recs = [r for r in recs if r.adjustment_type != AdjustmentType.KEEP]
        
        recs = [r for r in recs if r.confidence >= min_confidence]
        
        return sorted(recs, key=lambda r: r.confidence, reverse=True)
    
    def approve_recommendation(
        self,
        filter_name: str,
        approved_by: str = "operator",
    ) -> bool:
        """
        Approve a pending recommendation.
        
        Args:
            filter_name: Filter name
            approved_by: Who approved
            
        Returns:
            True if approved successfully
        """
        if filter_name not in self._pending_recommendations:
            logger.warning(f"No pending recommendation for {filter_name}")
            return False
        
        rec = self._pending_recommendations[filter_name]
        rec.approved = True
        rec.approved_at = datetime.now(timezone.utc)
        rec.approved_by = approved_by
        
        logger.info(f"Approved recommendation for {filter_name}: {rec.adjustment_type.value}")
        
        # Apply the recommendation (would integrate with config system)
        # self._apply_recommendation(rec)
        
        return True
    
    def reject_recommendation(self, filter_name: str) -> bool:
        """Reject and remove a pending recommendation."""
        if filter_name in self._pending_recommendations:
            del self._pending_recommendations[filter_name]
            logger.info(f"Rejected recommendation for {filter_name}")
            return True
        return False
    
    def generate_learning_report(
        self,
        period_days: int = 7,
    ) -> dict[str, Any]:
        """
        Generate a comprehensive learning report.
        
        Args:
            period_days: Period to analyze
            
        Returns:
            Report dictionary
        """
        summary = self._tracker.get_summary(period_days)
        filter_reports = self.get_all_filter_reports(period_days)
        recommendations = self.get_recommendations(min_confidence=0.5)
        
        # Sort filters by effectiveness
        filter_reports.sort(key=lambda r: r.effectiveness_score, reverse=True)
        
        return {
            "period_days": period_days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            
            # Summary
            "summary": summary,
            
            # Top performing filters
            "top_filters": [
                {
                    "name": r.filter_name,
                    "effectiveness": r.effectiveness_score,
                    "net_pnl": r.net_pnl_impact,
                }
                for r in filter_reports[:3]
            ],
            
            # Filters needing attention
            "filters_needing_attention": [
                {
                    "name": r.filter_name,
                    "effectiveness": r.effectiveness_score,
                    "issue": "Low effectiveness" if r.effectiveness_score < 0.3 else "High miss rate",
                }
                for r in filter_reports
                if r.effectiveness_score < 0.3 or r.blocked_hypothetical_win_rate > 0.6
            ],
            
            # Recommendations
            "recommendations": [r.to_dict() for r in recommendations],
            
            # Key insights
            "key_insights": self._generate_insights(summary, filter_reports),
        }
    
    def _generate_insights(
        self,
        summary: dict[str, Any],
        filter_reports: list[FilterPerformanceReport],
    ) -> list[str]:
        """Generate key insights from the analysis."""
        insights = []
        
        # Overall filter value
        net_value = summary.get("net_filter_value", 0)
        if net_value > 0:
            insights.append(f"Filters saved ${net_value:.0f} net over the period.")
        else:
            insights.append(f"Filters cost ${abs(net_value):.0f} in missed opportunities.")
        
        # Blocked win rate
        blocked_wr = summary.get("blocked_hypothetical_win_rate", 0)
        if blocked_wr > 0.5:
            insights.append(
                f"Blocked signals had {blocked_wr:.0%} hypothetical win rate - "
                f"consider relaxing filters."
            )
        elif blocked_wr < 0.3:
            insights.append(
                f"Blocked signals had only {blocked_wr:.0%} hypothetical win rate - "
                f"filters are effectively removing bad signals."
            )
        
        # Best and worst filters
        if filter_reports:
            best = filter_reports[0]
            worst = filter_reports[-1]
            
            if best.effectiveness_score > 0.7:
                insights.append(f"Most effective filter: {best.filter_name} ({best.effectiveness_score:.0%})")
            
            if worst.effectiveness_score < 0.3:
                insights.append(f"Least effective filter: {worst.filter_name} - review settings")
        
        return insights


# Global analytics instance
_analytics: Optional[FilterAnalytics] = None


def get_filter_analytics() -> FilterAnalytics:
    """Get the global filter analytics instance."""
    global _analytics
    if _analytics is None:
        _analytics = FilterAnalytics()
    return _analytics
