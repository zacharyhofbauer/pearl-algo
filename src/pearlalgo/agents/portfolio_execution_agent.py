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
from typing import Dict, List, Optional

import pandas as pd
from loguru import logger

from pearlalgo.agents.langgraph_state import (
    PositionDecision,
    TradingState,
    add_agent_reasoning,
)
from pearlalgo.brokers.base import Broker
from pearlalgo.brokers.factory import get_broker
from pearlalgo.core.events import OrderEvent
from pearlalgo.core.portfolio import Portfolio

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
        broker_name: str = "ibkr",
        config: Optional[Dict] = None,
    ):
        self.portfolio = portfolio
        self.config = config or {}
        self.broker_name = broker_name
        
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
        self.execution_delay = self.config.get("agents", {}).get(
            "portfolio_execution", {}
        ).get("execution_delay", 0.5)
        self.max_retries = self.config.get("agents", {}).get(
            "portfolio_execution", {}
        ).get("max_order_retries", 3)
        
        logger.info(
            f"PortfolioExecutionAgent initialized: broker={broker_name}"
        )
    
    async def execute_decisions(
        self, state: TradingState
    ) -> TradingState:
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
                        if (current_position.size > 0 and decision.size < 0) or \
                           (current_position.size < 0 and decision.size > 0):
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
        
        # Submit order
        try:
            order_id = self.broker.submit_order(order)
            decision.order_ids.append(order_id)
            decision.status = "submitted"
            
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
            metadata={"action": "exit", "reasoning": decision.reasoning if decision else "Position exit"},
        )
        
        try:
            order_id = self.broker.submit_order(order)
            if decision:
                decision.order_ids.append(order_id)
                decision.status = "submitted"
            
            state = add_agent_reasoning(
                state,
                "portfolio_execution_agent",
                f"Exit order submitted for {symbol}: {order_id}",
                level="info",
            )
        
        except Exception as e:
            logger.error(f"Failed to submit exit order for {symbol}: {e}", exc_info=True)
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
            order_id = self.broker.submit_order(order)
            decision.order_ids.append(order_id)
            decision.status = "submitted"
        
        except Exception as e:
            logger.error(f"Failed to submit reduce order for {symbol}: {e}", exc_info=True)
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
                "parent_order_id": decision.order_ids[0] if decision.order_ids else None,
            },
        )
        
        try:
            order_id = self.broker.submit_order(order)
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
                "parent_order_id": decision.order_ids[0] if decision.order_ids else None,
            },
        )
        
        try:
            order_id = self.broker.submit_order(order)
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

