"""
Paper Broker - Wraps Paper Trading Engines.

Provides a broker interface that uses internal paper trading engines
for realistic simulation without external broker dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, Iterable, Optional

from pearlalgo.brokers.base import Broker, BrokerConfig
from pearlalgo.brokers.interfaces import AccountSummary, MarginRequirements
from pearlalgo.core.events import FillEvent, OrderEvent
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.paper_trading.futures_engine import PaperFuturesEngine
from pearlalgo.paper_trading.options_engine import PaperOptionsEngine
from pearlalgo.paper_trading.fill_models import FillModelConfig
from pearlalgo.paper_trading.margin_models import FuturesMarginModel, OptionsMarginModel

logger = logging.getLogger(__name__)


class PaperBroker(Broker):
    """
    Paper broker that uses internal paper trading engines.

    Supports both futures and options trading through specialized engines.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        config: BrokerConfig | None = None,
        fill_config: Optional[FillModelConfig] = None,
        price_lookup: Optional[Callable[[str], Optional[float]]] = None,
        options_chain_lookup: Optional[Callable[[str], list[Dict]]] = None,
        deterministic: bool = False,
    ):
        """
        Initialize paper broker.

        Args:
            portfolio: Portfolio instance
            config: Broker configuration
            fill_config: Fill model configuration
            price_lookup: Function to get current price for a symbol
            options_chain_lookup: Function to get options chain for underlying
            deterministic: Enable deterministic mode for backtesting
        """
        super().__init__(portfolio, config)

        if fill_config is None:
            fill_config = FillModelConfig(deterministic=deterministic)

        # Initialize engines
        self.futures_engine = PaperFuturesEngine(
            portfolio=portfolio,
            fill_config=fill_config,
            price_lookup=price_lookup,
        )

        self.options_engine = PaperOptionsEngine(
            portfolio=portfolio,
            fill_config=fill_config,
            options_chain_lookup=options_chain_lookup,
        )

        # Track order IDs
        self._order_counter = 0
        self._orders: Dict[str, OrderEvent] = {}

        # Determine which engine to use based on symbol type
        self._futures_symbols = {"ES", "NQ", "MES", "MNQ", "CL", "GC", "MCL", "MGC"}
        self._options_symbols = set()  # Will be populated dynamically

    def _is_futures(self, symbol: str) -> bool:
        """Check if symbol is a futures contract."""
        symbol_base = symbol.split("_")[0].upper()
        return symbol_base in self._futures_symbols

    def _is_options(self, symbol: str) -> bool:
        """Check if symbol is an options contract."""
        # Check if it looks like an option (contains date/expiration info)
        return "_" in symbol and len(symbol.split("_")) >= 3

    def submit_order(self, order: OrderEvent) -> str:
        """
        Submit an order for execution.

        Args:
            order: OrderEvent to execute

        Returns:
            Order ID
        """
        self._order_counter += 1
        order_id = f"PAPER_{self._order_counter:06d}"
        self._orders[order_id] = order

        # Route to appropriate engine
        if self._is_options(order.symbol):
            fill = self.options_engine.submit_order(order)
        elif self._is_futures(order.symbol):
            fill = self.futures_engine.submit_order(order)
        else:
            # Default to futures for unknown symbols
            logger.warning(
                f"Unknown symbol type for {order.symbol}, using futures engine"
            )
            fill = self.futures_engine.submit_order(order)

        if fill:
            logger.info(
                f"Order {order_id} filled: {fill.side} {fill.quantity} "
                f"{fill.symbol} @ {fill.price:.4f}"
            )
        else:
            logger.info(f"Order {order_id} submitted and pending")

        return order_id

    def fetch_fills(self, since: datetime | None = None) -> Iterable[FillEvent]:
        """Retrieve fills from both engines."""
        futures_fills = self.futures_engine.get_fills(since=since)
        options_fills = self.options_engine.get_fills(since=since)

        # Combine and sort by timestamp
        all_fills = list(futures_fills) + list(options_fills)
        all_fills.sort(key=lambda f: f.timestamp)

        return all_fills

    def cancel_order(self, order_id: str) -> None:
        """Cancel an order (not fully supported in paper trading)."""
        if order_id in self._orders:
            logger.info(f"Cancelling order {order_id}")
            del self._orders[order_id]
        else:
            logger.warning(f"Order {order_id} not found")

    def sync_positions(self) -> Dict[str, float]:
        """Sync positions from both engines."""
        futures_positions = self.futures_engine.get_positions()
        options_positions = self.options_engine.get_positions()

        # Combine positions
        all_positions = {**futures_positions, **options_positions}
        return all_positions

    def get_account_summary(self) -> AccountSummary:
        """Get account summary with margin calculations."""
        # Get positions and calculate equity
        positions = self.sync_positions()
        cash = self.portfolio.cash

        # Calculate unrealized PnL (simplified - would need current prices)
        unrealized_pnl = sum(
            pos.realized_pnl for pos in self.portfolio.positions.values()
        )

        # Calculate margin used
        margin_used = 0.0
        futures_margin = FuturesMarginModel()
        options_margin = OptionsMarginModel()

        for symbol, quantity in positions.items():
            if self._is_futures(symbol):
                margin_req = futures_margin.get_margin_requirements(
                    symbol=symbol, quantity=quantity
                )
                if margin_req:
                    margin_used += margin_req.total_required
            elif self._is_options(symbol):
                # Simplified margin calculation for options
                pos = self.portfolio.positions.get(symbol)
                if pos and pos.avg_price > 0:
                    margin_req = options_margin.get_margin_requirements(
                        option_type="call",  # Would need to parse symbol
                        strike=0.0,  # Would need to parse
                        premium=pos.avg_price,
                        quantity=abs(quantity),
                        is_long=quantity > 0,
                    )
                    if margin_req:
                        margin_used += margin_req.total_required

        equity = cash + unrealized_pnl
        buying_power = equity - margin_used

        return AccountSummary(
            equity=equity,
            cash=cash,
            buying_power=max(0.0, buying_power),
            margin_used=margin_used,
            margin_available=max(0.0, buying_power),
            unrealized_pnl=unrealized_pnl,
            realized_pnl=sum(
                pos.realized_pnl for pos in self.portfolio.positions.values()
            ),
            timestamp=datetime.now(),
        )

    def get_margin_requirements(self, symbol: str) -> Optional[MarginRequirements]:
        """Get margin requirements for a symbol."""
        if self._is_futures(symbol):
            pos = self.portfolio.positions.get(symbol)
            if pos:
                margin_req = self.futures_engine.margin_model.get_margin_requirements(
                    symbol=symbol, quantity=abs(pos.size)
                )
                return MarginRequirements(
                    initial_margin=margin_req.initial_margin,
                    maintenance_margin=margin_req.maintenance_margin,
                    total_required=margin_req.total_required,
                    available_margin=0.0,  # Would need account equity
                )

        return None

    def update_price(self, symbol: str, price: float, atr: Optional[float] = None) -> None:
        """
        Update price for a symbol (triggers fills and mark-to-market).

        Args:
            symbol: Trading symbol
            price: Current market price
            atr: Average True Range (optional, for futures slippage)
        """
        if self._is_futures(symbol):
            self.futures_engine.update_price(symbol=symbol, price=price, atr=atr)
        # Options prices are updated via options chain updates

    def update_options_chain(self, underlying_symbol: str, chain: list[Dict]) -> None:
        """
        Update options chain for an underlying symbol.

        Args:
            underlying_symbol: Underlying symbol (e.g., 'QQQ')
            chain: List of option contracts
        """
        self.options_engine.update_options_chain(
            underlying_symbol=underlying_symbol, chain=chain
        )


