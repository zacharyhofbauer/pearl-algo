"""
Portfolio/Execution Agent - Final decision and order execution.

This agent is responsible for:
- Final action decision (combines signals + risk)
- Order placement via broker abstraction
- Position management
- Enhanced version of existing execution_agent.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional


try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import (
    PositionDecision,
    TradingState,
    add_agent_reasoning,
)
from pearlalgo.brokers.base import Broker
from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.events import OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.futures.performance import PerformanceRow, log_performance_row
from pearlalgo.utils.retry import CircuitBreaker, retry_with_backoff
from pearlalgo.utils.telegram_alerts import TelegramAlerts

logger = logging.getLogger(__name__)


class PortfolioExecutionAgent:
    """
    Portfolio/Execution Agent for LangGraph workflow.

    Makes final trading decisions and executes orders via broker abstraction.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        broker: Optional[Broker] = None,
        broker_name: str = "paper",
        config: Optional[Dict] = None,
        telegram_alerts: Optional[TelegramAlerts] = None,
    ):
        self.portfolio = portfolio
        self.config = config or {}
        self.broker_name = broker_name
        self.telegram_alerts = telegram_alerts
        
        # Check if signal-only mode is enabled
        self.signal_only = self.config.get("trading", {}).get("signal_only", False)

        # Initialize broker if not provided
        if broker:
            self.broker = broker
        else:
            self.broker = get_broker(
                broker_name=broker_name,
                portfolio=portfolio,
                config=config,
            )

        # Execution settings
        self.execution_delay = (
            self.config.get("agents", {})
            .get("portfolio_execution", {})
            .get("execution_delay", 0.5)
        )
        self.max_retries = (
            self.config.get("agents", {})
            .get("portfolio_execution", {})
            .get("max_order_retries", 3)
        )
        
        # Track entry times for performance logging
        self.entry_times: Dict[str, datetime] = {}
        self.entry_prices: Dict[str, float] = {}
        self.trade_reasons: Dict[str, str] = {}
        
        # Circuit breaker for broker API calls
        self.broker_circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            expected_exception=Exception,
        )

        logger.info(f"PortfolioExecutionAgent initialized: broker={broker_name}, signal_only={self.signal_only}")

    async def execute_decisions(self, state: TradingState) -> TradingState:
        """
        Execute position decisions and place orders.

        This is the main entry point called by the LangGraph workflow.
        """
        logger.info("PortfolioExecutionAgent: Executing position decisions")

        state = add_agent_reasoning(
            state,
            "portfolio_execution_agent",
            f"Executing {len(state.position_decisions)} position decisions",
            level="info",
        )

        # Check if trading is enabled
        if not state.trading_enabled or state.kill_switch_triggered:
            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                "Trading disabled or kill-switch triggered - skipping execution",
                level="warning",
            )
            return state

        # If signal-only mode, log signals without executing trades
        if self.signal_only:
            return await self._log_signals_only(state)

        # Execute each position decision
        for symbol, decision in state.position_decisions.items():
            try:
                # Check if we should execute
                if decision.status != "pending":
                    continue

                # Check current position
                current_position = self.portfolio.positions.get(symbol)

                # Determine action
                if decision.action == "enter_long" or decision.action == "enter_short":
                    # Check if we already have a position
                    if current_position and current_position.size != 0:
                        # Check if we need to reverse
                        if (current_position.size > 0 and decision.size < 0) or (
                            current_position.size < 0 and decision.size > 0
                        ):
                            # Exit existing position first
                            await self._exit_position(symbol, state, decision)
                            # Then enter new position
                            await self._enter_position(symbol, decision, state)
                        else:
                            # Same direction - skip or reduce/add
                            state = add_agent_reasoning(
                                state,
                                "portfolio_execution_agent",
                                f"Position already exists for {symbol}, skipping entry",
                                level="info",
                            )
                    else:
                        # Enter new position
                        await self._enter_position(symbol, decision, state)

                elif decision.action == "exit":
                    await self._exit_position(symbol, state, decision)

                elif decision.action == "reduce":
                    await self._reduce_position(symbol, decision, state)

                elif decision.action == "hold":
                    state = add_agent_reasoning(
                        state,
                        "portfolio_execution_agent",
                        f"Holding position for {symbol}",
                        level="debug",
                    )

            except Exception as e:
                error_msg = f"Error executing decision for {symbol}: {e}"
                logger.error(error_msg, exc_info=True)
                state.errors.append(error_msg)
                decision.status = "rejected"
                state = add_agent_reasoning(
                    state,
                    "portfolio_execution_agent",
                    error_msg,
                    level="error",
                    data={"symbol": symbol, "error": str(e)},
                )

        # Update portfolio equity curve
        if state.portfolio:
            current_equity = self._calculate_equity(state)
            state.equity_curve.append(current_equity)

        logger.info(
            f"PortfolioExecutionAgent: Executed {len([d for d in state.position_decisions.values() if d.status != 'pending'])} decisions"
        )

        return state

    async def _enter_position(
        self,
        symbol: str,
        decision: PositionDecision,
        state: TradingState,
    ) -> None:
        """Enter a new position."""
        logger.info(
            f"Entering {decision.action} position: {symbol} x{decision.size} @ ${decision.entry_price:.2f}"
        )

        state = add_agent_reasoning(
            state,
            "portfolio_execution_agent",
            f"Entering {decision.action} for {symbol}: {decision.size} contracts @ ${decision.entry_price:.2f}",
            level="info",
            data={
                "symbol": symbol,
                "action": decision.action,
                "size": decision.size,
                "price": decision.entry_price,
            },
        )

        # Create order event
        side = "BUY" if decision.size > 0 else "SELL"
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=abs(decision.size),
            order_type="MKT",
            limit_price=decision.entry_price,
            metadata={
                "stop_loss": decision.stop_loss,
                "take_profit": decision.take_profit,
                "risk_amount": decision.risk_amount,
                "reasoning": decision.reasoning,
            },
        )

        # Submit order with retry and circuit breaker
        try:
            order_id = self._submit_order_with_retry(order)
            decision.order_ids.append(order_id)
            decision.status = "submitted"
            
            # Track entry time and price for performance logging
            entry_time = datetime.now(timezone.utc)
            self.entry_times[symbol] = entry_time
            self.entry_prices[symbol] = decision.entry_price
            self.trade_reasons[symbol] = decision.reasoning

            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                f"Order submitted for {symbol}: {order_id}",
                level="info",
                data={"symbol": symbol, "order_id": order_id},
            )

            # Place stop loss order if provided
            if decision.stop_loss:
                await self._place_stop_loss(symbol, decision, state)

            # Place take profit order if provided
            if decision.take_profit:
                await self._place_take_profit(symbol, decision, state)
            
            # Log performance entry
            self._log_trade_entry(symbol, decision, state, entry_time)

        except Exception as e:
            logger.error(f"Failed to submit order for {symbol}: {e}", exc_info=True)
            decision.status = "rejected"
            raise

    async def _exit_position(
        self,
        symbol: str,
        state: TradingState,
        decision: Optional[PositionDecision] = None,
    ) -> None:
        """Exit an existing position."""
        current_position = self.portfolio.positions.get(symbol)
        if not current_position or current_position.size == 0:
            return

        logger.info(f"Exiting position: {symbol} x{current_position.size}")

        state = add_agent_reasoning(
            state,
            "portfolio_execution_agent",
            f"Exiting position for {symbol}: {current_position.size} contracts",
            level="info",
            data={"symbol": symbol, "size": current_position.size},
        )

        # Create exit order
        side = "SELL" if current_position.size > 0 else "BUY"
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=abs(current_position.size),
            order_type="MKT",
            limit_price=0.0,  # Market order
            metadata={
                "action": "exit",
                "reasoning": decision.reasoning if decision else "Position exit",
            },
        )

        try:
            exit_time = datetime.now(timezone.utc)
            order_id = self._submit_order_with_retry(order)
            if decision:
                decision.order_ids.append(order_id)
                decision.status = "submitted"

            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                f"Exit order submitted for {symbol}: {order_id}",
                level="info",
            )
            
            # Log performance exit
            self._log_trade_exit(symbol, state, exit_time, decision)

        except Exception as e:
            logger.error(
                f"Failed to submit exit order for {symbol}: {e}", exc_info=True
            )
            raise

    async def _reduce_position(
        self,
        symbol: str,
        decision: PositionDecision,
        state: TradingState,
    ) -> None:
        """Reduce an existing position."""
        current_position = self.portfolio.positions.get(symbol)
        if not current_position or current_position.size == 0:
            return

        reduce_size = abs(decision.size)
        if reduce_size >= abs(current_position.size):
            # Reducing entire position - use exit
            await self._exit_position(symbol, state, decision)
            return

        logger.info(f"Reducing position: {symbol} by {reduce_size}")

        # Create reduce order
        side = "SELL" if current_position.size > 0 else "BUY"
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=reduce_size,
            order_type="MKT",
            limit_price=decision.entry_price or 0.0,
            metadata={"action": "reduce", "reasoning": decision.reasoning},
        )

        try:
            order_id = self._submit_order_with_retry(order)
            decision.order_ids.append(order_id)
            decision.status = "submitted"

        except Exception as e:
            logger.error(
                f"Failed to submit reduce order for {symbol}: {e}", exc_info=True
            )
            raise

    async def _place_stop_loss(
        self,
        symbol: str,
        decision: PositionDecision,
        state: TradingState,
    ) -> None:
        """Place stop loss order."""
        if not decision.stop_loss:
            return

        current_position = self.portfolio.positions.get(symbol)
        if not current_position or current_position.size == 0:
            # Position not yet filled, will place after fill
            return

        logger.info(f"Placing stop loss for {symbol} @ ${decision.stop_loss:.2f}")

        side = "SELL" if current_position.size > 0 else "BUY"
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=abs(current_position.size),
            order_type="STP",
            limit_price=decision.stop_loss,
            metadata={
                "order_type": "stop_loss",
                "parent_order_id": decision.order_ids[0]
                if decision.order_ids
                else None,
            },
        )

        try:
            order_id = self._submit_order_with_retry(order)
            decision.order_ids.append(order_id)
            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                f"Stop loss order placed for {symbol}: {order_id}",
                level="info",
            )

        except Exception as e:
            logger.warning(f"Failed to place stop loss for {symbol}: {e}")

    async def _place_take_profit(
        self,
        symbol: str,
        decision: PositionDecision,
        state: TradingState,
    ) -> None:
        """Place take profit order."""
        if not decision.take_profit:
            return

        current_position = self.portfolio.positions.get(symbol)
        if not current_position or current_position.size == 0:
            # Position not yet filled, will place after fill
            return

        logger.info(f"Placing take profit for {symbol} @ ${decision.take_profit:.2f}")

        side = "SELL" if current_position.size > 0 else "BUY"
        order = OrderEvent(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            side=side,
            quantity=abs(current_position.size),
            order_type="LMT",
            limit_price=decision.take_profit,
            metadata={
                "order_type": "take_profit",
                "parent_order_id": decision.order_ids[0]
                if decision.order_ids
                else None,
            },
        )

        try:
            order_id = self._submit_order_with_retry(order)
            decision.order_ids.append(order_id)
            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                f"Take profit order placed for {symbol}: {order_id}",
                level="info",
            )

        except Exception as e:
            logger.warning(f"Failed to place take profit for {symbol}: {e}")

    def _calculate_equity(self, state: TradingState) -> float:
        """Calculate current portfolio equity."""
        if not state.portfolio:
            return 0.0

        equity = state.portfolio.cash

        # Add unrealized PnL from positions
        for symbol, position in state.portfolio.positions.items():
            if position.size != 0:
                market_data = state.market_data.get(symbol)
                if market_data:
                    current_price = market_data.close
                    equity += position.size * (current_price - position.avg_price)

        return equity
    
    def _log_trade_entry(
        self,
        symbol: str,
        decision: PositionDecision,
        state: TradingState,
        entry_time: datetime,
    ) -> None:
        """Log trade entry with all required performance fields."""
        try:
            # Get signal for additional context
            signal = state.signals.get(symbol)
            
            # Calculate drawdown remaining
            drawdown_remaining = None
            if state.risk_state:
                drawdown_remaining = state.risk_state.remaining_loss_buffer
            
            # Get trade reason from decision or signal
            trade_reason = decision.reasoning or (signal.reasoning if signal else None)
            
            # Create performance row
            perf_row = PerformanceRow(
                timestamp=entry_time,
                symbol=symbol,
                sec_type="FUT",
                strategy_name=signal.strategy_name if signal else "unknown",
                side=decision.action.replace("enter_", "").upper(),
                requested_size=decision.size,
                filled_size=decision.size,  # Will be updated when fill is confirmed
                entry_time=entry_time,
                entry_price=decision.entry_price,
                realized_pnl=None,  # Will be set on exit
                unrealized_pnl=None,
                fast_ma=signal.indicators.get("fast_ma") if signal else None,
                slow_ma=signal.indicators.get("slow_ma") if signal else None,
                risk_status=state.risk_state.status if state.risk_state else "UNKNOWN",
                drawdown_remaining=drawdown_remaining,
                trade_reason=trade_reason,
                emotion_state=None,  # Optional - can be added if tracking emotions
                notes=None,
            )
            
            log_performance_row(perf_row)
            
        except Exception as e:
            logger.warning(f"Failed to log trade entry for {symbol}: {e}")
    
    def _log_trade_exit(
        self,
        symbol: str,
        state: TradingState,
        exit_time: datetime,
        decision: Optional[PositionDecision] = None,
    ) -> None:
        """Log trade exit with all required performance fields."""
        try:
            # Get entry information
            entry_time = self.entry_times.get(symbol)
            entry_price = self.entry_prices.get(symbol)
            trade_reason = self.trade_reasons.get(symbol)
            
            if not entry_time or not entry_price:
                logger.warning(f"Missing entry information for {symbol}, skipping exit log")
                return
            
            # Get current position to calculate PnL
            position = self.portfolio.positions.get(symbol)
            if not position:
                return
            
            # Get exit price from market data or decision
            market_data = state.market_data.get(symbol)
            exit_price = market_data.close if market_data else entry_price
            
            # Calculate realized PnL
            realized_pnl = position.realized_pnl if position.realized_pnl else 0.0
            
            # Calculate drawdown remaining
            drawdown_remaining = None
            if state.risk_state:
                drawdown_remaining = state.risk_state.remaining_loss_buffer
            
            # Get signal for context
            signal = state.signals.get(symbol)
            
            # Create performance row for exit
            perf_row = PerformanceRow(
                timestamp=exit_time,
                symbol=symbol,
                sec_type="FUT",
                strategy_name=signal.strategy_name if signal else "unknown",
                side="EXIT",
                requested_size=0,
                filled_size=abs(position.size) if position else 0,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                unrealized_pnl=None,
                fast_ma=signal.indicators.get("fast_ma") if signal else None,
                slow_ma=signal.indicators.get("slow_ma") if signal else None,
                risk_status=state.risk_state.status if state.risk_state else "UNKNOWN",
                drawdown_remaining=drawdown_remaining,
                trade_reason=trade_reason,
                emotion_state=None,
                notes=None,
            )
            
            log_performance_row(perf_row)
            
            # Clear entry tracking
            self.entry_times.pop(symbol, None)
            self.entry_prices.pop(symbol, None)
            self.trade_reasons.pop(symbol, None)
            
        except Exception as e:
            logger.warning(f"Failed to log trade exit for {symbol}: {e}")
    
    async def _log_signals_only(self, state: TradingState) -> TradingState:
        """
        Log signals to performance CSV without executing trades.
        
        In signal-only mode, we track signals and calculate potential PnL
        without actually placing orders.
        """
        logger.info("PortfolioExecutionAgent: Signal-only mode - logging signals without execution")
        
        state = add_agent_reasoning(
            state,
            "portfolio_execution_agent",
            f"Signal-only mode: Logging {len(state.position_decisions)} signals",
            level="info",
        )
        
        for symbol, decision in state.position_decisions.items():
            try:
                # Get current market price
                market_data = state.market_data.get(symbol)
                if not market_data:
                    logger.warning(f"No market data for {symbol}, skipping signal log")
                    continue
                
                current_price = market_data.close
                entry_price = decision.entry_price or current_price
                
                # Calculate potential PnL (unrealized)
                # For signals, we calculate based on entry price vs current price
                direction = 1 if decision.action in ["enter_long", "long"] else -1
                size = abs(decision.size)
                unrealized_pnl = direction * size * (current_price - entry_price)
                
                # Get signal from state
                signal = state.signals.get(symbol)
                strategy_name = signal.strategy_name if signal else "unknown"
                
                # Create performance row for signal
                perf_row = PerformanceRow(
                    timestamp=datetime.now(timezone.utc),
                    symbol=symbol,
                    sec_type="FUT",
                    strategy_name=strategy_name,
                    side=decision.action.replace("enter_", "").upper(),
                    requested_size=size,
                    filled_size=0,  # No actual fill in signal-only mode
                    entry_time=datetime.now(timezone.utc),
                    entry_price=entry_price,
                    exit_price=None,
                    realized_pnl=None,
                    unrealized_pnl=unrealized_pnl,
                    risk_status=state.risk_state.status if state.risk_state else "UNKNOWN",
                    drawdown_remaining=None,
                    trade_reason=decision.reasoning or (signal.reasoning if signal else None),
                    notes="Signal-only mode - no trade executed",
                )
                
                # Log to CSV
                log_performance_row(perf_row)
                
                # Send Telegram notification with signal and PnL
                if self.telegram_alerts:
                    try:
                        pnl_emoji = "📈" if unrealized_pnl >= 0 else "📉"
                        message = (
                            f"{pnl_emoji} *Signal Logged*\n\n"
                            f"Symbol: {symbol}\n"
                            f"Direction: {decision.action.replace('enter_', '').upper()}\n"
                            f"Strategy: {strategy_name}\n"
                            f"Entry Price: ${entry_price:.2f}\n"
                            f"Size: {size} contracts\n"
                            f"Stop Loss: ${decision.stop_loss:.2f}\n"
                            f"Take Profit: ${decision.take_profit:.2f}\n"
                            f"Risk: {decision.risk_percent * 100:.2f}%\n"
                            f"Potential P&L: ${unrealized_pnl:,.2f}\n"
                        )
                        if decision.reasoning:
                            message += f"\nReasoning: {decision.reasoning[:150]}..."
                        await self.telegram_alerts.send_message(message)
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram notification for signal: {e}")
                
                decision.status = "logged"
                
                state = add_agent_reasoning(
                    state,
                    "portfolio_execution_agent",
                    f"Logged signal for {symbol}: {decision.action} @ ${entry_price:.2f}, "
                    f"potential P&L: ${unrealized_pnl:,.2f}",
                    level="info",
                    data={
                        "symbol": symbol,
                        "action": decision.action,
                        "entry_price": entry_price,
                        "unrealized_pnl": unrealized_pnl,
                    },
                )
                
            except Exception as e:
                error_msg = f"Error logging signal for {symbol}: {e}"
                logger.error(error_msg, exc_info=True)
                state.errors.append(error_msg)
                decision.status = "error"
        
        logger.info(f"PortfolioExecutionAgent: Logged {len([d for d in state.position_decisions.values() if d.status == 'logged'])} signals")
        return state
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(Exception,),
    )
    def _submit_order_with_retry(self, order: OrderEvent) -> str:
        """
        Submit order with retry logic and circuit breaker protection.
        
        Args:
            order: OrderEvent to submit
            
        Returns:
            Order ID from broker
            
        Raises:
            Exception: If all retry attempts fail or circuit breaker is open
        """
        return self.broker_circuit_breaker.call(
            self.broker.submit_order,
            order,
        )
