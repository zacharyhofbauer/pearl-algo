"""
Analysis Engine - Orchestrates multi-dimensional analysis using Claude.

Coordinates signal, system, market, and code analyzers to provide
comprehensive monitoring of the trading agent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

if TYPE_CHECKING:
    from pearlalgo.utils.claude_client import ClaudeClient


class AnalysisEngine:
    """
    Orchestrates multi-dimensional analysis using Claude.
    
    Coordinates:
    - Signal analyzer: Signal quality & win rate
    - System analyzer: Health, errors, circuit breakers
    - Market analyzer: Regime detection, volatility
    - Code analyzer: Code quality, technical debt
    """
    
    def __init__(
        self,
        claude_client: Optional["ClaudeClient"] = None,
        code_analysis_interval_hours: int = 1,
    ):
        """
        Initialize analysis engine.
        
        Args:
            claude_client: Claude API client
            code_analysis_interval_hours: How often to run code analysis
        """
        self._claude = claude_client
        self._code_analysis_interval = timedelta(hours=code_analysis_interval_hours)
        self._last_code_analysis: Optional[datetime] = None
        
        # Import analyzers (lazy to avoid circular imports)
        self._signal_analyzer = None
        self._system_analyzer = None
        self._market_analyzer = None
        self._code_analyzer = None
    
    def _ensure_analyzers(self) -> None:
        """Ensure analyzers are initialized."""
        if self._signal_analyzer is None:
            from pearlalgo.claude_monitor.analyzers.signal_analyzer import SignalAnalyzer
            from pearlalgo.claude_monitor.analyzers.system_analyzer import SystemAnalyzer
            from pearlalgo.claude_monitor.analyzers.market_analyzer import MarketAnalyzer
            from pearlalgo.claude_monitor.analyzers.code_analyzer import CodeAnalyzer
            
            self._signal_analyzer = SignalAnalyzer(self._claude)
            self._system_analyzer = SystemAnalyzer(self._claude)
            self._market_analyzer = MarketAnalyzer(self._claude)
            self._code_analyzer = CodeAnalyzer(self._claude)
    
    def set_claude_client(self, client: "ClaudeClient") -> None:
        """Set or update the Claude client."""
        self._claude = client
        # Reset analyzers to use new client
        self._signal_analyzer = None
        self._system_analyzer = None
        self._market_analyzer = None
        self._code_analyzer = None
    
    async def analyze_all(
        self,
        agent_state: Dict[str, Any],
        signals_data: Optional[List[Dict[str, Any]]] = None,
        performance_data: Optional[Dict[str, Any]] = None,
        market_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run all analysis dimensions.
        
        Args:
            agent_state: Current agent state from state.json
            signals_data: Recent signals from signals.jsonl
            performance_data: Performance metrics
            market_data: Current market data
            
        Returns:
            Combined analysis results from all dimensions
        """
        self._ensure_analyzers()
        
        results = {
            "timestamp": get_utc_timestamp(),
            "status": "completed",
        }
        
        # Run parallel analysis for efficiency
        try:
            # Create analysis tasks
            tasks = {
                "signals": self._analyze_signals(agent_state, signals_data, performance_data),
                "system": self._analyze_system(agent_state),
                "market": self._analyze_market(agent_state, market_data),
            }
            
            # Code analysis runs less frequently
            if self._should_run_code_analysis():
                tasks["code"] = self._analyze_code()
            
            # Run all tasks concurrently
            task_results = await asyncio.gather(
                *[task for task in tasks.values()],
                return_exceptions=True
            )
            
            # Map results back to keys
            for i, key in enumerate(tasks.keys()):
                result = task_results[i]
                if isinstance(result, Exception):
                    logger.error(f"Analysis error for {key}: {result}")
                    results[key] = {
                        "status": "error",
                        "error": str(result),
                    }
                else:
                    results[key] = result
            
        except Exception as e:
            logger.error(f"Analysis engine error: {e}")
            results["status"] = "partial_error"
            results["error"] = str(e)
        
        return results
    
    async def _analyze_signals(
        self,
        agent_state: Dict[str, Any],
        signals_data: Optional[List[Dict[str, Any]]],
        performance_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run signal analysis."""
        try:
            return await self._signal_analyzer.analyze(
                agent_state=agent_state,
                signals=signals_data,
                performance=performance_data,
            )
        except Exception as e:
            logger.error(f"Signal analysis failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _analyze_system(
        self,
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run system health analysis."""
        try:
            return await self._system_analyzer.analyze(agent_state)
        except Exception as e:
            logger.error(f"System analysis failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _analyze_market(
        self,
        agent_state: Dict[str, Any],
        market_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run market conditions analysis."""
        try:
            return await self._market_analyzer.analyze(
                agent_state=agent_state,
                market_data=market_data,
            )
        except Exception as e:
            logger.error(f"Market analysis failed: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _analyze_code(self) -> Dict[str, Any]:
        """Run code quality analysis."""
        try:
            self._last_code_analysis = datetime.now(timezone.utc)
            return await self._code_analyzer.analyze()
        except Exception as e:
            logger.error(f"Code analysis failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def _should_run_code_analysis(self) -> bool:
        """Check if code analysis should run."""
        if self._last_code_analysis is None:
            return True
        
        elapsed = datetime.now(timezone.utc) - self._last_code_analysis
        return elapsed >= self._code_analysis_interval
    
    async def analyze_signals_only(
        self,
        agent_state: Dict[str, Any],
        signals_data: Optional[List[Dict[str, Any]]] = None,
        performance_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run signal analysis only."""
        self._ensure_analyzers()
        return await self._analyze_signals(agent_state, signals_data, performance_data)
    
    async def analyze_system_only(
        self,
        agent_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run system analysis only."""
        self._ensure_analyzers()
        return await self._analyze_system(agent_state)
    
    async def analyze_market_only(
        self,
        agent_state: Dict[str, Any],
        market_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run market analysis only."""
        self._ensure_analyzers()
        return await self._analyze_market(agent_state, market_data)
    
    async def analyze_code_only(self) -> Dict[str, Any]:
        """Run code analysis only."""
        self._ensure_analyzers()
        return await self._analyze_code()
    
    def get_status(self) -> Dict[str, Any]:
        """Get analysis engine status."""
        return {
            "claude_available": self._claude is not None,
            "last_code_analysis": self._last_code_analysis.isoformat() if self._last_code_analysis else None,
            "analyzers_initialized": self._signal_analyzer is not None,
        }





