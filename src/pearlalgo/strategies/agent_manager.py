"""
Multi-Strategy Agent Manager

Manages multiple trading strategies as independent agents, similar to Lux Algo Chart Prime.
Each agent runs its own strategy with dedicated configuration, state, and performance tracking.

Like Lux Algo Chart Prime, this framework allows:
- Multiple strategies for different market conditions
- Independent agent deployment and management
- Strategy-specific configurations and parameters
- Parallel execution with resource management
- Performance isolation and tracking
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Protocol
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import threading
import time

from pearlalgo.utils.logger import logger
from pearlalgo.config.config_loader import load_service_config


class StrategyAgent(Protocol):
    """Protocol for strategy agents that can run independently."""

    @property
    def name(self) -> str:
        """Unique agent name."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        ...

    def analyze(self, market_data: Dict) -> List[Dict]:
        """Analyze market data and return signals."""
        ...

    def get_config(self) -> Dict[str, Any]:
        """Get agent configuration."""
        ...

    def get_status(self) -> AgentStatus:
        """Get current agent status."""
        ...


@dataclass
class AgentStatus:
    """Status information for a strategy agent."""

    name: str
    is_active: bool = True
    last_signal_time: Optional[datetime] = None
    total_signals: int = 0
    active_positions: int = 0
    performance_metrics: Dict[str, Any] = field(default_factory=dict)
    health_status: str = "healthy"  # healthy, warning, error
    last_error: Optional[str] = None
    config_hash: str = ""  # For detecting config changes


@dataclass
class AgentConfig:
    """Configuration for a strategy agent."""

    name: str
    strategy_class: str  # Import path to strategy class
    enabled: bool = True
    priority: int = 1  # Execution priority (1=high, 5=low)
    max_positions: int = 1  # Maximum concurrent positions
    risk_allocation: float = 0.1  # % of total capital
    market_conditions: List[str] = field(default_factory=list)  # When to activate
    excluded_conditions: List[str] = field(default_factory=list)  # When to deactivate
    config_overrides: Dict[str, Any] = field(default_factory=dict)  # Strategy-specific config


class StrategyRegistry:
    """Registry for managing available strategy agents."""

    def __init__(self):
        self._agents: Dict[str, StrategyAgent] = {}
        self._configs: Dict[str, AgentConfig] = {}
        self._status_cache: Dict[str, AgentStatus] = {}

    def register_agent(self, agent: StrategyAgent, config: AgentConfig) -> None:
        """Register a strategy agent."""
        if config.name in self._agents:
            logger.warning(f"Agent {config.name} already registered, overwriting")

        self._agents[config.name] = agent
        self._configs[config.name] = config
        self._status_cache[config.name] = AgentStatus(name=config.name)
        logger.info(f"Registered agent: {config.name}")

    def unregister_agent(self, name: str) -> None:
        """Unregister a strategy agent."""
        if name in self._agents:
            del self._agents[name]
            del self._configs[name]
            del self._status_cache[name]
            logger.info(f"Unregistered agent: {name}")

    def get_agent(self, name: str) -> Optional[StrategyAgent]:
        """Get a registered agent by name."""
        return self._agents.get(name)

    def get_config(self, name: str) -> Optional[AgentConfig]:
        """Get agent configuration."""
        return self._configs.get(name)

    def get_status(self, name: str) -> Optional[AgentStatus]:
        """Get agent status."""
        return self._status_cache.get(name)

    def list_agents(self) -> List[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def get_active_agents(self) -> List[StrategyAgent]:
        """Get all enabled agents."""
        active = []
        for name, config in self._configs.items():
            if config.enabled and name in self._agents:
                active.append(self._agents[name])
        return active

    def update_status(self, name: str, status: AgentStatus) -> None:
        """Update agent status."""
        if name in self._status_cache:
            self._status_cache[name] = status


class AgentManager:
    """
    Manages multiple strategy agents with parallel execution and coordination.

    Similar to how Lux Algo Chart Prime manages multiple automated strategies,
    this manager coordinates independent agents that can run simultaneously.
    """

    def __init__(self, max_workers: int = 4):
        self.registry = StrategyRegistry()
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="strategy-agent")
        self._running = False
        self._shutdown_event = threading.Event()

        # Coordination settings
        self.conflict_resolution = "priority"  # priority, first_signal, consensus
        self.resource_limits = {
            "max_total_positions": 5,
            "max_risk_allocation": 0.5,  # 50% total risk
        }

        logger.info(f"AgentManager initialized with {max_workers} workers")

    def register_agent(self, agent_class: type, config: AgentConfig) -> None:
        """Register a strategy agent class with configuration."""
        try:
            # Instantiate the agent
            agent_instance = agent_class(config=config)
            self.registry.register_agent(agent_instance, config)
        except Exception as e:
            logger.error(f"Failed to register agent {config.name}: {e}")
            raise

    def start_agents(self) -> None:
        """Start all enabled agents."""
        if self._running:
            logger.warning("Agent manager already running")
            return

        self._running = True
        self._shutdown_event.clear()
        logger.info("Starting strategy agents...")

        # Start coordination loop in background
        coordination_thread = threading.Thread(
            target=self._coordination_loop,
            name="agent-coordinator",
            daemon=True
        )
        coordination_thread.start()

    def stop_agents(self) -> None:
        """Stop all agents gracefully."""
        logger.info("Stopping strategy agents...")
        self._running = False
        self._shutdown_event.set()
        self._executor.shutdown(wait=True)
        logger.info("All agents stopped")

    def analyze_market_data(self, market_data: Dict) -> List[Dict]:
        """
        Analyze market data with all active agents.

        Returns consolidated signals with conflict resolution.
        """
        if not self._running:
            return []

        active_agents = self.registry.get_active_agents()
        if not active_agents:
            return []

        # Submit analysis tasks to thread pool
        future_to_agent = {}
        for agent in active_agents:
            if self._should_run_agent(agent, market_data):
                future = self._executor.submit(self._analyze_with_agent, agent, market_data)
                future_to_agent[future] = agent

        # Collect results
        all_signals = []
        for future in as_completed(future_to_agent, timeout=30):
            agent = future_to_agent[future]
            try:
                signals = future.result()
                if signals:
                    # Tag signals with agent info
                    for signal in signals:
                        signal['agent_name'] = agent.name
                        signal['agent_priority'] = self.registry.get_config(agent.name).priority
                    all_signals.extend(signals)

                    # Update agent status
                    status = self.registry.get_status(agent.name)
                    if status:
                        status.last_signal_time = datetime.now(timezone.utc)
                        status.total_signals += len(signals)
                        self.registry.update_status(agent.name, status)

            except Exception as e:
                logger.error(f"Agent {agent.name} analysis failed: {e}")
                # Update agent health status
                status = self.registry.get_status(agent.name)
                if status:
                    status.health_status = "error"
                    status.last_error = str(e)
                    self.registry.update_status(agent.name, status)

        # Apply conflict resolution and resource limits
        resolved_signals = self._resolve_conflicts(all_signals)
        filtered_signals = self._apply_resource_limits(resolved_signals)

        return filtered_signals

    def _coordination_loop(self) -> None:
        """Background coordination loop for agent management."""
        while not self._shutdown_event.is_set():
            try:
                # Health checks and status updates
                self._perform_health_checks()

                # Dynamic agent activation/deactivation based on market conditions
                self._update_agent_activation()

                # Resource usage monitoring
                self._monitor_resources()

            except Exception as e:
                logger.error(f"Coordination loop error: {e}")

            # Sleep for coordination interval
            self._shutdown_event.wait(60)  # Check every minute

    def _should_run_agent(self, agent: StrategyAgent, market_data: Dict) -> bool:
        """Determine if agent should run based on market conditions and config."""
        config = self.registry.get_config(agent.name)
        if not config:
            return False

        # Check market condition filters
        if config.market_conditions:
            current_conditions = self._detect_market_conditions(market_data)
            if not any(cond in current_conditions for cond in config.market_conditions):
                return False

        # Check exclusion conditions
        if config.excluded_conditions:
            current_conditions = self._detect_market_conditions(market_data)
            if any(cond in current_conditions for cond in config.excluded_conditions):
                return False

        return True

    def _analyze_with_agent(self, agent: StrategyAgent, market_data: Dict) -> List[Dict]:
        """Wrapper for agent analysis with error handling."""
        try:
            return agent.analyze(market_data)
        except Exception as e:
            logger.error(f"Agent {agent.name} analysis error: {e}")
            return []

    def _resolve_conflicts(self, signals: List[Dict]) -> List[Dict]:
        """Resolve conflicting signals from multiple agents."""
        if not signals:
            return signals

        if self.conflict_resolution == "priority":
            # Sort by priority (lower number = higher priority)
            signals.sort(key=lambda s: s.get('agent_priority', 5))
            return self._remove_duplicate_signals(signals)

        elif self.conflict_resolution == "first_signal":
            # Take first signal for each direction/symbol
            return self._remove_duplicate_signals(signals)

        elif self.conflict_resolution == "consensus":
            # Require multiple agents to agree
            return self._consensus_filter(signals)

        return signals

    def _apply_resource_limits(self, signals: List[Dict]) -> List[Dict]:
        """Apply resource limits (position limits, risk allocation)."""
        if not signals:
            return signals

        # Count current positions across all agents
        current_positions = sum(
            status.active_positions
            for status in self.registry._status_cache.values()
        )

        # Filter signals based on limits
        filtered_signals = []
        total_risk_allocated = 0.0

        for signal in signals:
            agent_config = self.registry.get_config(signal.get('agent_name', ''))

            # Check position limit
            if current_positions + len(filtered_signals) >= self.resource_limits['max_total_positions']:
                break

            # Check risk allocation
            if agent_config:
                signal_risk = signal.get('risk_allocation', agent_config.risk_allocation)
                if total_risk_allocated + signal_risk > self.resource_limits['max_risk_allocation']:
                    continue

                total_risk_allocated += signal_risk

            filtered_signals.append(signal)

        return filtered_signals

    def _detect_market_conditions(self, market_data: Dict) -> List[str]:
        """Detect current market conditions for agent activation."""
        conditions = []

        # Basic condition detection (can be extended)
        df = market_data.get('df')
        if df is not None and len(df) > 0:
            # Volatility conditions
            returns = df['close'].pct_change()
            volatility = returns.std()
            if volatility > 0.002:
                conditions.append('high_volatility')
            elif volatility < 0.0005:
                conditions.append('low_volatility')

            # Trend conditions
            sma_20 = df['close'].rolling(20).mean()
            if df['close'].iloc[-1] > sma_20.iloc[-1]:
                conditions.append('bull_trend')
            else:
                conditions.append('bear_trend')

        return conditions

    def _remove_duplicate_signals(self, signals: List[Dict]) -> List[Dict]:
        """Remove duplicate/conflicting signals."""
        seen_keys = set()
        unique_signals = []

        for signal in signals:
            # Create unique key based on direction and symbol
            key = f"{signal.get('direction', '')}_{signal.get('symbol', '')}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_signals.append(signal)

        return unique_signals

    def _consensus_filter(self, signals: List[Dict]) -> List[Dict]:
        """Require consensus from multiple agents for signal validity."""
        # Group signals by direction/symbol
        signal_groups = {}
        for signal in signals:
            key = f"{signal.get('direction', '')}_{signal.get('symbol', '')}"
            if key not in signal_groups:
                signal_groups[key] = []
            signal_groups[key].append(signal)

        # Keep signals with consensus (2+ agents agree)
        consensus_signals = []
        for group_signals in signal_groups.values():
            if len(group_signals) >= 2:
                # Take the highest confidence signal from the group
                best_signal = max(group_signals, key=lambda s: s.get('confidence', 0))
                consensus_signals.append(best_signal)

        return consensus_signals

    def _perform_health_checks(self) -> None:
        """Perform health checks on all agents."""
        for agent_name in self.registry.list_agents():
            try:
                agent = self.registry.get_agent(agent_name)
                status = self.registry.get_status(agent_name)

                if agent and status:
                    # Update health status based on recent activity
                    if status.last_signal_time:
                        time_since_signal = (
                            datetime.now(timezone.utc) - status.last_signal_time
                        ).total_seconds()

                        if time_since_signal > 3600:  # No signals for 1 hour
                            status.health_status = "warning"
                        else:
                            status.health_status = "healthy"
                    else:
                        status.health_status = "idle"

                    self.registry.update_status(agent_name, status)

            except Exception as e:
                logger.error(f"Health check failed for {agent_name}: {e}")

    def _update_agent_activation(self) -> None:
        """Dynamically activate/deactivate agents based on conditions."""
        # This could be extended to activate agents based on:
        # - Time of day
        # - Market regime
        # - Performance metrics
        # - Risk limits
        pass

    def _monitor_resources(self) -> None:
        """Monitor system resources and agent performance."""
        # Track CPU, memory usage
        # Monitor agent performance metrics
        # Adjust resource allocation dynamically
        pass

    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        return {
            "total_agents": len(self.registry.list_agents()),
            "active_agents": len(self.registry.get_active_agents()),
            "running": self._running,
            "agent_statuses": {
                name: self.registry.get_status(name).__dict__
                for name in self.registry.list_agents()
            },
            "resource_limits": self.resource_limits,
            "conflict_resolution": self.conflict_resolution,
        }


# Global agent manager instance
agent_manager = AgentManager()


def get_agent_manager() -> AgentManager:
    """Get the global agent manager instance."""
    return agent_manager