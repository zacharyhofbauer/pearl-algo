from __future__ import annotations

import pandas as pd
from typing import Iterable

from pearlalgo.brokers.base import Broker
from pearlalgo.core.events import OrderEvent
from pearlalgo.risk.limits import RiskGuard, RiskLimits


class ExecutionAgent:
    """
    Translates strategy signals into orders via a Broker.
    Backtest/paper are default; live trading must be explicitly selected upstream.
    """

    def __init__(
        self,
        broker: Broker,
        symbol: str,
        profile: str = "backtest",
        risk_guard: RiskGuard | None = None,
    ):
        self.broker = broker
        self.symbol = symbol
        self.profile = profile
        self.risk_guard = risk_guard or RiskGuard(RiskLimits())

    def _orders_from_signals(self, signals: pd.DataFrame) -> Iterable[OrderEvent]:
        for ts, row in signals.iterrows():
            signal_val = row.get("entry", 0)
            if signal_val is None or pd.isna(signal_val) or signal_val == 0:
                continue
            side = "BUY" if float(signal_val) > 0 else "SELL"
            qty = abs(float(row.get("size", 1)))
            sec_type = row.get("sec_type") or "STK"
            expiry = row.get("expiry")
            local_symbol = row.get("local_symbol")
            trading_class = row.get("trading_class")
            price = float(row.get("Close", row.get("close", row.get("price", 0.0))))
            # Futures do not allow fractional contracts; round up to at least 1
            if str(sec_type).upper().startswith("FUT") and qty < 1:
                qty = 1
            yield OrderEvent(
                timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                symbol=self.symbol,
                side=side,
                quantity=qty,
                order_type="MKT",
                limit_price=price,
                metadata={
                    "profile": self.profile,
                    "sec_type": sec_type,
                    "last_price": price,
                    "expiry": expiry,
                    "local_symbol": local_symbol,
                    "trading_class": trading_class,
                },
            )

    def execute(self, signals: pd.DataFrame) -> list[str]:
        if self.profile != "live":
            # Safety: warn that this agent is not routing to a live venue
            print(f"ExecutionAgent running in profile '{self.profile}'; live trading disabled.")
        order_ids: list[str] = []
        for order in self._orders_from_signals(signals):
            # Risk guard pre-check; broker may also enforce downstream.
            self.risk_guard.check_order(order, last_price=order.limit_price)
            order_id = self.broker.submit_order(order)
            order_ids.append(order_id)
        return order_ids

    def execute_advanced(
        self,
        signals: pd.DataFrame,
        order_type: str = "market",
        use_stop_loss: bool = True,
        use_take_profit: bool = True,
        max_slippage: float = 0.001,
    ) -> list[str]:
        """
        Execute orders with advanced order types.
        
        Args:
            signals: DataFrame with signals including stop_loss and take_profit columns
            order_type: "market", "limit", "stop", "stop_limit"
            use_stop_loss: Whether to place stop loss orders
            use_take_profit: Whether to place take profit orders
            max_slippage: Maximum acceptable slippage (0.1% default)
        """
        if self.profile != "live":
            print(f"ExecutionAgent running in profile '{self.profile}'; live trading disabled.")
        
        order_ids: list[str] = []
        
        for ts, row in signals.iterrows():
            signal_val = row.get("entry", 0)
            if signal_val is None or pd.isna(signal_val) or signal_val == 0:
                continue
            
            side = "BUY" if float(signal_val) > 0 else "SELL"
            qty = abs(float(row.get("size", 1)))
            sec_type = row.get("sec_type") or "FUT"
            price = float(row.get("Close", row.get("close", row.get("price", 0.0))))
            
            # Futures do not allow fractional contracts
            if str(sec_type).upper().startswith("FUT") and qty < 1:
                qty = 1
            
            # Main entry order
            if order_type == "limit":
                limit_price = row.get("limit_price", price)
                order = OrderEvent(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    symbol=self.symbol,
                    side=side,
                    quantity=qty,
                    order_type="LMT",
                    limit_price=limit_price,
                    metadata={
                        "profile": self.profile,
                        "sec_type": sec_type,
                        "last_price": price,
                        "expiry": row.get("expiry"),
                        "local_symbol": row.get("local_symbol"),
                        "trading_class": row.get("trading_class"),
                    },
                )
            else:  # market order
                order = OrderEvent(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    symbol=self.symbol,
                    side=side,
                    quantity=qty,
                    order_type="MKT",
                    limit_price=price,
                    metadata={
                        "profile": self.profile,
                        "sec_type": sec_type,
                        "last_price": price,
                        "expiry": row.get("expiry"),
                        "local_symbol": row.get("local_symbol"),
                        "trading_class": row.get("trading_class"),
                    },
                )
            
            # Risk guard pre-check
            self.risk_guard.check_order(order, last_price=price)
            order_id = self.broker.submit_order(order)
            order_ids.append(order_id)
            
            # Place stop loss order if specified
            if use_stop_loss and "stop_loss" in row and pd.notna(row.get("stop_loss")):
                stop_price = float(row.get("stop_loss"))
                stop_order = OrderEvent(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    symbol=self.symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=qty,
                    order_type="STP",
                    limit_price=stop_price,
                    metadata={
                        "profile": self.profile,
                        "sec_type": sec_type,
                        "parent_order_id": order_id,
                        "order_type": "stop_loss",
                    },
                )
                stop_order_id = self.broker.submit_order(stop_order)
                order_ids.append(stop_order_id)
            
            # Place take profit order if specified
            if use_take_profit and "take_profit" in row and pd.notna(row.get("take_profit")):
                tp_price = float(row.get("take_profit"))
                tp_order = OrderEvent(
                    timestamp=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                    symbol=self.symbol,
                    side="SELL" if side == "BUY" else "BUY",
                    quantity=qty,
                    order_type="LMT",
                    limit_price=tp_price,
                    metadata={
                        "profile": self.profile,
                        "sec_type": sec_type,
                        "parent_order_id": order_id,
                        "order_type": "take_profit",
                    },
                )
                tp_order_id = self.broker.submit_order(tp_order)
                order_ids.append(tp_order_id)
        
        return order_ids
