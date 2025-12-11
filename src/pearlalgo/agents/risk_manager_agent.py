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
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

import pandas as pd


try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)

from pearlalgo.agents.langgraph_state import (
    MarketData,
    PositionDecision,
    Signal,
    TradingState,
    add_agent_reasoning,
)
# Futures risk modules removed - will be replaced with options-specific risk management
from pearlalgo.core.portfolio import Portfolio
# TODO: Create options-specific risk state and position sizing
from pearlalgo.utils.telegram_alerts import TelegramAlerts
from pearlalgo.risk.options_risk import OptionsRiskCalculator
from pearlalgo.core.signal_router import SignalRouter

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
        telegram_alerts: Optional[TelegramAlerts] = None,
    ):
        self.portfolio = portfolio
        self.profile = profile or load_profile()
        self.config = config or {}
        self.telegram_alerts = telegram_alerts

        # Options risk calculator
        self.options_risk_calculator = OptionsRiskCalculator()

        # Signal router for asset type detection
        self.signal_router = SignalRouter()

        # Configurable risk (from config, defaults to hardcoded values)
        risk_config = self.config.get("risk", {})
        self.max_risk_per_trade = risk_config.get("max_risk_per_trade", self.MAX_RISK_PER_TRADE)
        self.max_drawdown = risk_config.get("max_drawdown", self.MAX_DRAWDOWN)
        self.volatility_target_min = risk_config.get("volatility_target", {}).get("min", self.VOLATILITY_TARGET_MIN)
        self.volatility_target_max = risk_config.get("volatility_target", {}).get("max", self.VOLATILITY_TARGET_MAX)
        
        # Separate risk rules for futures vs options
        self.futures_max_risk = risk_config.get("futures", {}).get("max_risk_per_trade", self.max_risk_per_trade)
        self.options_max_risk = risk_config.get("options", {}).get("max_risk_per_trade", self.max_risk_per_trade * 0.5)  # Options: 50% of futures risk
        
        # Cool-down tracking
        self.cooldown_until: Optional[datetime] = None
        self.last_trade_time: Optional[datetime] = None
        self.consecutive_losses = 0
        self.max_consecutive_losses = risk_config.get("circuit_breakers", {}).get("max_consecutive_losses", 5)
        self.cooldown_minutes = risk_config.get("circuit_breakers", {}).get("cooldown_minutes", 30)

        # Risk state tracking
        self.day_start_equity = portfolio.cash
        self.peak_equity = portfolio.cash
        self.trades_today = 0

        logger.info(
            f"RiskManagerAgent initialized: max_risk={self.max_risk_per_trade}, "
            f"max_drawdown={self.max_drawdown}, volatility_target={self.volatility_target_min}-{self.volatility_target_max}"
        )

    async def evaluate_risk(self, state: TradingState) -> TradingState:
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

        # Check cool-down period
        if self.cooldown_until and datetime.now(timezone.utc) < self.cooldown_until:
            state.trading_enabled = False
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Trading disabled: Cool-down period active until {self.cooldown_until}",
                level="warning",
                data={"cooldown_until": self.cooldown_until.isoformat()},
            )
            return state
        else:
            self.cooldown_until = None  # Clear expired cooldown

        # Check kill-switch (15% drawdown)
        current_equity = self.portfolio.cash + realized_pnl + unrealized_pnl
        drawdown = (
            (self.peak_equity - current_equity) / self.peak_equity
            if self.peak_equity > 0
            else 0.0
        )

        if drawdown >= self.max_drawdown:
            state.kill_switch_triggered = True
            state.trading_enabled = False
            reason = f"Drawdown {drawdown * 100:.2f}% >= {self.max_drawdown * 100}%"
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"KILL-SWITCH TRIGGERED: {reason}",
                level="error",
                data={"drawdown": drawdown, "max_drawdown": self.max_drawdown},
            )
            # Trigger cooldown after kill-switch
            self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)
            logger.critical(f"Kill-switch triggered: {drawdown * 100:.2f}% drawdown")
            
            # Send Telegram notification
            if self.telegram_alerts:
                try:
                    await self.telegram_alerts.notify_kill_switch(reason)
                except Exception as e:
                    logger.warning(f"Failed to send Telegram kill-switch notification: {e}")

        # Update peak equity
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # Compute risk state - TODO: Replace with options-specific risk state
        risk_state = None  # TODO: Implement options risk state computation
        # risk_state = compute_risk_state(
        #     self.profile,
        #     day_start_equity=self.day_start_equity,
        #     realized_pnl=realized_pnl,
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
                warning_msg = f"Signal for {symbol} BLOCKED: risk state = {risk_state.status}"
                state = add_agent_reasoning(
                    state,
                    "risk_manager_agent",
                    warning_msg,
                    level="warning",
                    data={"symbol": symbol, "risk_status": risk_state.status},
                )
                # Send Telegram notification for risk warning
                if self.telegram_alerts:
                    try:
                        await self.telegram_alerts.notify_risk_warning(
                            warning_msg, risk_status=risk_state.status
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send Telegram risk warning: {e}")
                continue

            # Get market data for price
            market_data = state.market_data.get(symbol)
            if not market_data:
                continue

            price = market_data.close

            # Determine asset type
            is_futures = self.signal_router.is_futures(symbol)
            is_options = self.signal_router.is_options(symbol)
            
            # Use appropriate risk rules
            max_risk = self.futures_max_risk if is_futures else self.options_max_risk
            
            # Calculate position size with volatility targeting and risk limit
            position_size = self._calculate_position_size(
                symbol, signal, price, risk_state, current_equity, state.market_data,
                is_futures=is_futures, is_options=is_options, max_risk=max_risk
            )

            # Calculate stop loss and take profit (with ATR if available)
            stop_loss, take_profit = self._calculate_stop_take_profit(
                symbol, signal, price, position_size, state.market_data
            )

            # Calculate risk amount
            risk_amount = abs(position_size * (price - stop_loss)) if stop_loss else 0.0
            risk_percent = risk_amount / current_equity if current_equity > 0 else 0.0

            # Enforce max risk per trade (configurable, default 2%)
            if risk_percent > self.max_risk_per_trade:
                # Reduce position size to meet risk limit
                max_risk_amount = current_equity * max_risk
                if stop_loss and abs(price - stop_loss) > 0:
                    max_size = int(max_risk_amount / abs(price - stop_loss))
                    position_size = max_size if position_size > 0 else -max_size
                    risk_amount = abs(position_size * (price - stop_loss))
                    risk_percent = (
                        risk_amount / current_equity if current_equity > 0 else 0.0
                    )

                state = add_agent_reasoning(
                    state,
                    "risk_manager_agent",
                    f"Position size reduced for {symbol} to meet {max_risk * 100:.1f}% risk limit",
                    level="info",
                    data={
                        "symbol": symbol,
                        "risk_percent": risk_percent,
                        "position_size": position_size,
                        "max_risk_per_trade": self.max_risk_per_trade,
                    },
                )

            # Check for averaging down (not allowed)
            current_position = self.portfolio.positions.get(symbol)
            if current_position and current_position.size != 0:
                # Check if new position would average down
                if (
                    current_position.size > 0
                    and position_size > 0
                    and price < current_position.avg_price
                ) or (
                    current_position.size < 0
                    and position_size < 0
                    and price > current_position.avg_price
                ):
                    if not self.ALLOW_AVERAGING_DOWN:
                        state = add_agent_reasoning(
                            state,
                            "risk_manager_agent",
                            f"Signal for {symbol} BLOCKED: Averaging down not allowed",
                            level="warning",
                            data={
                                "symbol": symbol,
                                "current_price": price,
                                "avg_price": current_position.avg_price,
                            },
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
                reasoning=f"Risk-approved: {risk_percent * 100:.2f}% risk, stop at ${stop_loss:.2f}",
            )

            state.position_decisions[symbol] = decision

            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Risk-approved position for {symbol}: {position_size} contracts, "
                f"{risk_percent * 100:.2f}% risk, stop=${stop_loss:.2f}",
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
        risk_state: Optional[object],  # TODO: Replace with OptionsRiskState
        current_equity: float,
        market_data_history: Optional[Dict[str, MarketData]] = None,
        is_options: bool = True,  # Changed from is_futures
        is_options: bool = False,
        max_risk: float = None,
    ) -> int:
        """
        Calculate position size with volatility targeting and max risk per trade.

        Uses ATR or realized volatility for volatility-targeted position sizing.
        Falls back to fixed risk percentage if volatility data unavailable.
        """
        # Position sizing - TODO: Replace with options-specific position sizing
        base_size = 1  # Placeholder - will be replaced with options position sizing
        # base_size = compute_position_size(
        #     symbol, signal.side, self.profile, risk_state, price=price
        # )

        # Calculate volatility-targeted size if market data available
        volatility_size = None
        if market_data_history:
            atr = self._calculate_atr(symbol, market_data_history)
            if atr and atr > 0:
                # Target volatility: 0.5-1% of equity per day
                target_volatility = current_equity * (self.volatility_target_min + self.volatility_target_max) / 2
                # Position size based on ATR
                volatility_size = int(target_volatility / atr)
                if signal.side == "short":
                    volatility_size = -volatility_size

        # Use volatility size if available, otherwise use base size
        position_size = volatility_size if volatility_size is not None else base_size

        # Enforce max risk per trade (asset-specific)
        if max_risk is None:
            max_risk = self.futures_max_risk if is_futures else self.options_max_risk
            
        if signal.stop_loss:
            max_risk_amount = current_equity * max_risk
            risk_per_contract = abs(price - signal.stop_loss)

            if risk_per_contract > 0:
                max_size = int(max_risk_amount / risk_per_contract)
                # Apply limit while preserving direction
                if position_size > 0:
                    position_size = min(position_size, max_size)
                elif position_size < 0:
                    position_size = max(position_size, -max_size)

        return position_size
    
    def _calculate_atr(self, symbol: str, market_data_history: Dict[str, MarketData], period: int = 14) -> Optional[float]:
        """
        Calculate Average True Range (ATR) from market data history.
        
        Args:
            symbol: Symbol to calculate ATR for
            market_data_history: Dictionary of MarketData objects (by timestamp or index)
            period: ATR period (default 14)
            
        Returns:
            ATR value or None if insufficient data
        """
        try:
            # Convert market data to DataFrame for ATR calculation
            data_list = []
            for md in list(market_data_history.values())[-period * 2:]:  # Get enough data
                if md.symbol == symbol:
                    data_list.append({
                        'high': md.high,
                        'low': md.low,
                        'close': md.close,
                    })
            
            if len(data_list) < period + 1:
                return None
            
            df = pd.DataFrame(data_list)
            
            # Calculate True Range
            df['prev_close'] = df['close'].shift(1)
            df['tr1'] = df['high'] - df['low']
            df['tr2'] = abs(df['high'] - df['prev_close'])
            df['tr3'] = abs(df['low'] - df['prev_close'])
            df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            
            # Calculate ATR as moving average of TR
            atr = df['tr'].tail(period).mean()
            
            return float(atr) if not pd.isna(atr) else None
            
        except Exception as e:
            logger.warning(f"Failed to calculate ATR for {symbol}: {e}")
            return None

    def _calculate_stop_take_profit(
        self,
        symbol: str,
        signal: Signal,
        price: float,
        position_size: int,
        market_data_history: Optional[Dict[str, MarketData]] = None,
    ) -> tuple[float, float]:
        """
        Calculate stop loss and take profit levels.

        Uses ATR-based method if available, otherwise fixed percentage.
        """
        # Use signal's stop/target if available
        stop_loss = signal.stop_loss
        take_profit = signal.take_profit

        # Calculate ATR for ATR-based stops
        atr = None
        if market_data_history:
            atr = self._calculate_atr(symbol, market_data_history)

        # If not provided, calculate based on ATR or fixed percentage
        if not stop_loss:
            if atr:
                # ATR-based stop: 2x ATR
                atr_multiplier = self.config.get("risk", {}).get("stop_loss", {}).get("atr_multiplier", 2.0)
                if position_size > 0:  # Long
                    stop_loss = price - (atr * atr_multiplier)
                else:  # Short
                    stop_loss = price + (atr * atr_multiplier)
            else:
            # Default: 1% stop loss
                fixed_percent = self.config.get("risk", {}).get("stop_loss", {}).get("fixed_percent", 0.01)
            if position_size > 0:  # Long
                    stop_loss = price * (1 - fixed_percent)
            else:  # Short
                    stop_loss = price * (1 + fixed_percent)

        if not take_profit:
            # Default: 2:1 risk/reward (configurable)
            risk_reward_ratio = self.config.get("risk", {}).get("take_profit", {}).get("risk_reward_ratio", 2.0)
            risk = abs(price - stop_loss)
            if position_size > 0:  # Long
                take_profit = price + (risk * risk_reward_ratio)
            else:  # Short
                take_profit = price - (risk * risk_reward_ratio)

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
        max_daily_loss = self.config.get("risk", {}).get("circuit_breakers", {}).get("max_daily_loss", 2500.0)
        if state.daily_pnl <= -abs(max_daily_loss):
            state.trading_enabled = False
            self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Circuit breaker: Daily loss limit reached (${state.daily_pnl:.2f})",
                level="error",
                data={"cooldown_until": self.cooldown_until.isoformat()},
            )
            return False

        # Check max consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            state.trading_enabled = False
            self.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)
            state = add_agent_reasoning(
                state,
                "risk_manager_agent",
                f"Circuit breaker: Max consecutive losses reached ({self.consecutive_losses})",
                level="error",
                data={"cooldown_until": self.cooldown_until.isoformat()},
            )
            return False

        return True
    
    def record_trade_result(self, pnl: float):
        """
        Record trade result for consecutive loss tracking.
        
        Args:
            pnl: Profit/loss from the trade
        """
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0  # Reset on win
        
        self.last_trade_time = datetime.now(timezone.utc)
