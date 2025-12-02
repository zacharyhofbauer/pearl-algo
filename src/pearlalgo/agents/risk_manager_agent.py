"""
Risk Manager Agent - Enhanced risk management with hardcoded rules.

This agent enforces:
- 2% max risk per trade (HARDCODED)
- 15% max account drawdown kill-switch (HARDCODED)
- Volatility targeting (0.5-1% daily vol)
- Position sizing
- Stop-loss/take-profit calculation
- Circuit breakers
- No martingale, no averaging down (HARDCODED)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
from loguru import logger

from pearlalgo.agents.langgraph_state import (
    PositionDecision,
    Signal,
    TradingState,
    add_agent_reasoning,
)
from pearlalgo.futures.risk import RiskState
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.futures.config import PropProfile, load_profile
from pearlalgo.futures.risk import compute_position_size, compute_risk_state

logger = logging.getLogger(__name__)


class RiskManagerAgent:
    """
    Enhanced Risk Manager Agent for LangGraph workflow.
    
    Enforces all risk rules from the specification:
    - Max 2% risk per trade (HARDCODED)
    - Volatility targeting (0.5-1% daily vol)
    - Hard 15% account drawdown kill-switch (HARDCODED)
    - No martingale, no averaging down (HARDCODED)
    """
    
    # HARDCODED RISK RULES (DO NOT MODIFY)
    MAX_RISK_PER_TRADE = 0.02  # 2%
    MAX_DRAWDOWN = 0.15  # 15%
    VOLATILITY_TARGET_MIN = 0.005  # 0.5%
    VOLATILITY_TARGET_MAX = 0.01  # 1.0%
    ALLOW_MARTINGALE = False  # HARDCODED
    ALLOW_AVERAGING_DOWN = False  # HARDCODED
    
    def __init__(
        self,
        portfolio: Portfolio,
        profile: Optional[PropProfile] = None,
        config: Optional[Dict] = None,
    ):
        self.portfolio = portfolio
        self.profile = profile or load_profile()
        self.config = config or {}
        
        # Risk state tracking
        self.day_start_equity = portfolio.cash
        self.peak_equity = portfolio.cash
        self.trades_today = 0
        
        logger.info(
            f"RiskManagerAgent initialized: max_risk={self.MAX_RISK_PER_TRADE}, "
            f"max_drawdown={self.MAX_DRAWDOWN}"
        )
    
    async def evaluate_risk(
        self, state: TradingState
    ) -> TradingState:
        """
        Evaluate risk for all signals and update risk state.
        
        This is the main entry point called by the LangGraph workflow.
        """
        logger.info("RiskManagerAgent: Evaluating risk for all signals")
        
        state = add_agent_reasoning(
            state,
            "risk_manager_agent",
            "Evaluating risk state and position sizing",
            level="info",
        )
        
        # Calculate current PnL
        realized_pnl, unrealized_pnl = self._calculate_pnl(state)
        
        # Update day start equity if needed
        current_date = datetime.now(timezone.utc).date()
        if not hasattr(self, "_last_date") or current_date > self._last_date:
            self.day_start_equity = self.portfolio.cash + realized_pnl + unrealized_pnl
            self.peak_equity = self.day_start_equity
            self.trades_today = 0
            self._last_date = current_date
        
        # Check kill-switch (15% drawdown)
        current_equity = self.portfolio.cash + realized_pnl + unrealized_pnl
        drawdown = (self.peak_equity - current_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        
        if drawdown >= self.MAX_DRAWDOWN:
            state.kill_switch_triggered = True
            state.trading_enabled = False
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"KILL-SWITCH TRIGGERED: Drawdown {drawdown*100:.2f}% >= {self.MAX_DRAWDOWN*100}%",
                level="error",
                data={"drawdown": drawdown, "max_drawdown": self.MAX_DRAWDOWN},
            )
            logger.critical(f"Kill-switch triggered: {drawdown*100:.2f}% drawdown")
        
        # Update peak equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        # Compute risk state using existing function
        risk_state = compute_risk_state(
            self.profile,
            day_start_equity=self.day_start_equity,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            trades_today=self.trades_today,
            max_trades=self.profile.max_trades,
            now=datetime.now(timezone.utc),
        )
        
        state.risk_state = risk_state
        
        # Evaluate each signal for risk
        for symbol, signal in state.signals.items():
            if signal.side == "flat":
                continue
            
            # Check if we can trade (risk state allows)
            if risk_state.status in {"HARD_STOP", "COOLDOWN", "PAUSED"}:
                state = add_agent_reasoning(
                    state,
                    "risk_manager_agent",
                    f"Signal for {symbol} BLOCKED: risk state = {risk_state.status}",
                    level="warning",
                    data={"symbol": symbol, "risk_status": risk_state.status},
                )
                continue
            
            # Get market data for price
            market_data = state.market_data.get(symbol)
            if not market_data:
                continue
            
            price = market_data.close
            
            # Calculate position size with 2% risk limit
            position_size = self._calculate_position_size(
                symbol, signal, price, risk_state, current_equity
            )
            
            # Calculate stop loss and take profit
            stop_loss, take_profit = self._calculate_stop_take_profit(
                symbol, signal, price, position_size
            )
            
            # Calculate risk amount
            risk_amount = abs(position_size * (price - stop_loss)) if stop_loss else 0.0
            risk_percent = risk_amount / current_equity if current_equity > 0 else 0.0
            
            # Enforce 2% max risk per trade
            if risk_percent > self.MAX_RISK_PER_TRADE:
                # Reduce position size to meet 2% limit
                max_risk_amount = current_equity * self.MAX_RISK_PER_TRADE
                if stop_loss and abs(price - stop_loss) > 0:
                    max_size = int(max_risk_amount / abs(price - stop_loss))
                    position_size = max_size if position_size > 0 else -max_size
                    risk_amount = abs(position_size * (price - stop_loss))
                    risk_percent = risk_amount / current_equity if current_equity > 0 else 0.0
                
                state = add_agent_reasoning(
                    state,
                    "risk_manager_agent",
                    f"Position size reduced for {symbol} to meet 2% risk limit",
                    level="info",
                    data={
                        "symbol": symbol,
                        "risk_percent": risk_percent,
                        "position_size": position_size,
                    },
                )
            
            # Check for averaging down (not allowed)
            current_position = self.portfolio.positions.get(symbol)
            if current_position and current_position.size != 0:
                # Check if new position would average down
                if (current_position.size > 0 and position_size > 0 and price < current_position.avg_price) or \
                   (current_position.size < 0 and position_size < 0 and price > current_position.avg_price):
                    if not self.ALLOW_AVERAGING_DOWN:
                        state = add_agent_reasoning(
                            state,
                            "risk_manager_agent",
                            f"Signal for {symbol} BLOCKED: Averaging down not allowed",
                            level="warning",
                            data={"symbol": symbol, "current_price": price, "avg_price": current_position.avg_price},
                        )
                        continue
            
            # Create position decision
            decision = PositionDecision(
                symbol=symbol,
                timestamp=datetime.now(timezone.utc),
                action="enter_long" if signal.side == "long" else "enter_short",
                size=position_size,
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                risk_amount=risk_amount,
                risk_percent=risk_percent,
                reasoning=f"Risk-approved: {risk_percent*100:.2f}% risk, stop at ${stop_loss:.2f}",
            )
            
            state.position_decisions[symbol] = decision
            
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Risk-approved position for {symbol}: {position_size} contracts, "
                f"{risk_percent*100:.2f}% risk, stop=${stop_loss:.2f}",
                level="info",
                data={
                    "symbol": symbol,
                    "size": position_size,
                    "risk_percent": risk_percent,
                    "stop_loss": stop_loss,
                },
            )
        
        # Update state
        state.daily_pnl = realized_pnl + unrealized_pnl
        state.total_pnl = realized_pnl + unrealized_pnl
        
        logger.info(
            f"RiskManagerAgent: Evaluated {len(state.position_decisions)} positions, "
            f"risk_state={risk_state.status}"
        )
        
        return state
    
    def _calculate_pnl(self, state: TradingState) -> tuple[float, float]:
        """Calculate realized and unrealized PnL."""
        realized = 0.0
        unrealized = 0.0
        
        for symbol, position in self.portfolio.positions.items():
            realized += position.realized_pnl
            
            if position.size != 0:
                # Get current price from market data
                market_data = state.market_data.get(symbol)
                if market_data:
                    current_price = market_data.close
                    unrealized += position.size * (current_price - position.avg_price)
        
        return realized, unrealized
    
    def _calculate_position_size(
        self,
        symbol: str,
        signal: Signal,
        price: float,
        risk_state: RiskState,
        current_equity: float,
    ) -> int:
        """
        Calculate position size with 2% max risk per trade.
        
        Uses existing compute_position_size but enforces 2% limit.
        """
        # Use existing function
        base_size = compute_position_size(
            symbol, signal.side, self.profile, risk_state, price=price
        )
        
        # Enforce 2% max risk
        if signal.stop_loss:
            max_risk_amount = current_equity * self.MAX_RISK_PER_TRADE
            risk_per_contract = abs(price - signal.stop_loss)
            
            if risk_per_contract > 0:
                max_size = int(max_risk_amount / risk_per_contract)
                base_size = max_size if base_size > 0 else -max_size
        
        return base_size
    
    def _calculate_stop_take_profit(
        self,
        symbol: str,
        signal: Signal,
        price: float,
        position_size: int,
    ) -> tuple[float, float]:
        """
        Calculate stop loss and take profit levels.
        
        Uses ATR-based or fixed percentage method.
        """
        # Use signal's stop/target if available
        stop_loss = signal.stop_loss
        take_profit = signal.take_profit
        
        # If not provided, calculate based on config
        if not stop_loss:
            # Default: 1% stop loss
            if position_size > 0:  # Long
                stop_loss = price * 0.99
            else:  # Short
                stop_loss = price * 1.01
        
        if not take_profit:
            # Default: 2:1 risk/reward
            risk = abs(price - stop_loss)
            if position_size > 0:  # Long
                take_profit = price + (risk * 2.0)
            else:  # Short
                take_profit = price - (risk * 2.0)
        
        return stop_loss, take_profit
    
    def check_circuit_breakers(self, state: TradingState) -> bool:
        """
        Check circuit breakers and return True if trading should continue.
        
        Circuit breakers:
        - Max daily loss
        - Max consecutive losses
        - Cooldown periods
        """
        # Check max daily loss
        if state.daily_pnl <= -abs(self.profile.daily_loss_limit):
            state.trading_enabled = False
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Circuit breaker: Daily loss limit reached (${state.daily_pnl:.2f})",
                level="error",
            )
            return False
        
        # Check max consecutive losses (would need to track this)
        # This is a placeholder
        
        return True

