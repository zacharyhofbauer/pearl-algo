"""
LangGraph Workflow - Orchestrates multi-agent trading system.

Defines the stateful workflow graph connecting all 4 agents:
1. Market Data Agent
2. Quant Research Agent
3. Risk Manager Agent
4. Portfolio/Execution Agent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from langgraph.graph import END, START, StateGraph

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import TradingState, create_initial_state
from pearlalgo.agents.market_data_agent import MarketDataAgent
from pearlalgo.agents.portfolio_execution_agent import PortfolioExecutionAgent
from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.risk_manager_agent import RiskManagerAgent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.utils.telegram_alerts import TelegramAlerts
from pearlalgo.futures.signal_tracker import SignalTracker
from pearlalgo.futures.exit_signals import ExitSignalGenerator

logger = logging.getLogger(__name__)


class TradingWorkflow:
    """
    LangGraph workflow for multi-agent trading system.

    Workflow:
    1. Market Data Agent -> Fetch live data
    2. Quant Research Agent -> Generate signals
    3. Risk Manager Agent -> Evaluate risk and position sizing
    4. Portfolio/Execution Agent -> Execute trades
    """

    def __init__(
        self,
        symbols: list[str],
        portfolio: Portfolio,
        strategy: str = "sr",
        config: Optional[Dict] = None,
    ):
        self.symbols = symbols
        self.portfolio = portfolio
        self.strategy = strategy
        self.config = config or {}

        # Initialize Telegram alerts if enabled
        self.telegram_alerts = None
        alerts_config = self.config.get("alerts", {})
        telegram_config = alerts_config.get("telegram", {})
        if telegram_config.get("enabled", False):
            bot_token = telegram_config.get("bot_token", "")
            chat_id = telegram_config.get("chat_id", "")
            if bot_token and chat_id:
                try:
                    self.telegram_alerts = TelegramAlerts(
                        bot_token=bot_token,
                        chat_id=chat_id,
                        enabled=True,
                    )
                    logger.info("Telegram alerts initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize Telegram alerts: {e}")
                    self.telegram_alerts = None

        # Initialize agents
        self.market_data_agent = MarketDataAgent(
            symbols=symbols,
            config=config,
        )

        self.quant_research_agent = QuantResearchAgent(
            symbols=symbols,
            strategy=strategy,
            config=config,
            telegram_alerts=self.telegram_alerts,
        )

        self.risk_manager_agent = RiskManagerAgent(
            portfolio=portfolio,
            config=config,
            telegram_alerts=self.telegram_alerts,
        )

        self.portfolio_execution_agent = PortfolioExecutionAgent(
            portfolio=portfolio,
            config=config,
            telegram_alerts=self.telegram_alerts,
        )

        # Initialize signal tracker and exit signal generator
        self.signal_tracker = SignalTracker()
        self.exit_signal_generator = ExitSignalGenerator(
            signal_tracker=self.signal_tracker
        )

        # Build workflow graph
        self.workflow = self._build_workflow()

        logger.info(
            f"TradingWorkflow initialized: symbols={symbols}, "
            f"strategy={strategy}"
        )

    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow."""
        # Create state graph
        workflow = StateGraph(TradingState)

        # Add nodes (agents)
        workflow.add_node("market_data", self._market_data_node)
        workflow.add_node("quant_research", self._quant_research_node)
        workflow.add_node("risk_manager", self._risk_manager_node)
        workflow.add_node("portfolio_execution", self._portfolio_execution_node)
        workflow.add_node("exit_signals", self._exit_signals_node)

        # Define edges (workflow)
        workflow.add_edge(START, "market_data")
        workflow.add_edge("market_data", "quant_research")
        workflow.add_edge("quant_research", "risk_manager")
        workflow.add_edge("risk_manager", "portfolio_execution")
        workflow.add_edge("portfolio_execution", "exit_signals")
        workflow.add_edge("exit_signals", END)

        # Compile workflow
        return workflow.compile()

    async def _market_data_node(self, state: TradingState) -> TradingState:
        """Market Data Agent node."""
        logger.debug("Workflow: Market Data Agent")
        state.current_step = "market_data"
        return await self.market_data_agent.fetch_live_data(state)

    async def _quant_research_node(self, state: TradingState) -> TradingState:
        """Quant Research Agent node."""
        logger.debug("Workflow: Quant Research Agent")
        state.current_step = "quant_research"
        return await self.quant_research_agent.generate_signals(state)

    async def _risk_manager_node(self, state: TradingState) -> TradingState:
        """Risk Manager Agent node."""
        logger.debug("Workflow: Risk Manager Agent")
        state.current_step = "risk_manager"
        return await self.risk_manager_agent.evaluate_risk(state)

    async def _portfolio_execution_node(self, state: TradingState) -> TradingState:
        """Portfolio/Execution Agent node."""
        logger.debug("Workflow: Portfolio/Execution Agent")
        state.current_step = "portfolio_execution"
        result_state = await self.portfolio_execution_agent.execute_decisions(state)
        
        # Track new signals in signal tracker
        for symbol, decision in result_state.position_decisions.items():
            if decision.status == "logged" and decision.action in ["enter_long", "enter_short"]:
                signal = result_state.signals.get(symbol)
                if signal:
                    direction = "long" if decision.action == "enter_long" else "short"
                    self.signal_tracker.add_signal(
                        symbol=symbol,
                        direction=direction,
                        entry_price=decision.entry_price,
                        size=abs(decision.size),
                        stop_loss=decision.stop_loss,
                        take_profit=decision.take_profit,
                        strategy_name=signal.strategy_name,
                        reasoning=signal.reasoning,
                    )
        
        return result_state

    async def _exit_signals_node(self, state: TradingState) -> TradingState:
        """Exit Signals node - checks for stop/target/time exits."""
        logger.debug("Workflow: Exit Signals")
        state.current_step = "exit_signals"
        
        # Update PnL for all tracked signals
        self.exit_signal_generator.update_tracked_pnl(state)
        
        # Generate exit signals
        exit_signals = self.exit_signal_generator.generate_exit_signals(state)
        
        # Add exit signals to state and send Telegram alerts
        for symbol, exit_signal in exit_signals.items():
            state.signals[symbol] = exit_signal
            
            # Remove from tracker
            tracked_signal = self.signal_tracker.remove_signal(symbol)
            if tracked_signal:
                logger.info(
                    f"Exit signal generated for {symbol}: "
                    f"PnL=${tracked_signal.unrealized_pnl:.2f}, "
                    f"reason={exit_signal.reasoning}"
                )
                
                # Send Telegram alert
                if self.telegram_alerts:
                    try:
                        exit_type = exit_signal.indicators.get("exit_type", "unknown")
                        exit_price = exit_signal.entry_price  # Exit price
                        entry_price = exit_signal.indicators.get("entry_price", exit_price)
                        realized_pnl = tracked_signal.unrealized_pnl
                        
                        if exit_type == "stop_loss":
                            await self.telegram_alerts.notify_stop_loss(
                                symbol=symbol,
                                direction=tracked_signal.direction,
                                entry_price=entry_price,
                                stop_price=tracked_signal.stop_loss or exit_price,
                                size=tracked_signal.size,
                                realized_pnl=realized_pnl,
                            )
                        elif exit_type == "take_profit":
                            await self.telegram_alerts.notify_take_profit(
                                symbol=symbol,
                                direction=tracked_signal.direction,
                                entry_price=entry_price,
                                target_price=tracked_signal.take_profit or exit_price,
                                size=tracked_signal.size,
                                realized_pnl=realized_pnl,
                            )
                        else:
                            # Generic exit
                            hold_duration = str(
                                datetime.now(timezone.utc) - tracked_signal.timestamp
                            )
                            await self.telegram_alerts.notify_exit(
                                symbol=symbol,
                                direction=tracked_signal.direction,
                                entry_price=entry_price,
                                exit_price=exit_price,
                                size=tracked_signal.size,
                                realized_pnl=realized_pnl,
                                hold_duration=hold_duration,
                                exit_reason=exit_signal.reasoning,
                            )
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram exit alert: {e}")
        
        return state

    async def run_cycle(self, state: Optional[TradingState] = None) -> TradingState:
        """
        Run a single trading cycle through the workflow.

        Returns the final state after all agents have processed.
        """
        if state is None:
            state = create_initial_state(
                portfolio=self.portfolio,
                config=self.config,
            )

        # Run workflow
        try:
            final_state = await self.workflow.ainvoke(state)
            return final_state
        except Exception as e:
            logger.error(f"Error in workflow cycle: {e}", exc_info=True)
            state.errors.append(str(e))
            return state

    async def run_continuous(
        self,
        interval: int = 60,
        max_cycles: Optional[int] = None,
        shutdown_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Run workflow continuously with specified interval.

        Args:
            interval: Seconds between cycles
            max_cycles: Maximum number of cycles (None for infinite)
            shutdown_check: Optional callable that returns True to stop the workflow
        """
        logger.info(
            f"Starting continuous workflow: interval={interval}s, "
            f"max_cycles={max_cycles or 'infinite'}"
        )

        state = create_initial_state(
            portfolio=self.portfolio,
            config=self.config,
        )

        cycle_count = 0

        try:
            while True:
                # Check for shutdown request
                if shutdown_check and shutdown_check():
                    logger.info("Shutdown requested - stopping workflow")
                    break

                if max_cycles and cycle_count >= max_cycles:
                    logger.info(f"Reached max cycles: {max_cycles}")
                    break

                cycle_count += 1
                logger.info(f"Starting cycle #{cycle_count}")

                # Run workflow cycle
                result = await self.run_cycle(state)

                # LangGraph returns a dict, convert back to TradingState if needed
                if isinstance(result, dict):
                    from pearlalgo.agents.langgraph_state import TradingState

                    state = TradingState(**result)
                else:
                    state = result

                # Check for kill-switch
                if state.kill_switch_triggered:
                    logger.critical("Kill-switch triggered - stopping workflow")
                    break

                # Wait for next cycle (check shutdown during sleep)
                if interval > 0:
                    # Sleep in smaller chunks to check shutdown more frequently
                    sleep_chunks = max(1, interval // 5)  # Check every 1/5 of interval
                    for _ in range(5):
                        await asyncio.sleep(sleep_chunks)
                        if shutdown_check and shutdown_check():
                            logger.info("Shutdown requested during sleep - stopping workflow")
                            return

        except KeyboardInterrupt:
            logger.info("Workflow interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in continuous workflow: {e}", exc_info=True)
            raise
        finally:
            logger.info(f"Workflow stopped after {cycle_count} cycles")

    def run_cycle_sync(self, state: Optional[TradingState] = None) -> TradingState:
        """
        Synchronous wrapper for run_cycle.

        Useful for testing or when async is not available.
        """
        return asyncio.run(self.run_cycle(state))


def create_workflow(
    symbols: list[str],
    portfolio: Portfolio,
    strategy: str = "sr",
    config: Optional[Dict] = None,
) -> TradingWorkflow:
    """Factory function to create a trading workflow."""
    return TradingWorkflow(
        symbols=symbols,
        portfolio=portfolio,
        strategy=strategy,
        config=config,
    )
