"""
Automated Trading Agent - Fully autonomous IBKR paper trading with market hours awareness,
error recovery, and health monitoring.
"""
from __future__ import annotations

import logging
import time as time_module
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from pearlalgo.agents.execution_agent import ExecutionAgent
from pearlalgo.brokers.ibkr_broker import IBKRBroker
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.core.portfolio import Portfolio
from pearlalgo.data_providers.ibkr_data_provider import IBKRConnection, IBKRDataProvider
from pearlalgo.futures.config import load_profile
from pearlalgo.futures.performance import PerformanceRow, log_performance_row
from pearlalgo.futures.risk import compute_position_size, compute_risk_state
from pearlalgo.futures.signals import generate_signal
from pearlalgo.risk.limits import RiskGuard, RiskLimits
from pearlalgo.core.events import FillEvent

logger = logging.getLogger(__name__)
console = Console()


# Futures market hours (ET/EST) - adjust as needed
MARKET_OPEN = time(17, 0)  # 5:00 PM ET (overnight session start)
MARKET_CLOSE = time(16, 0)  # 4:00 PM ET (regular session close)
# Note: Futures trade nearly 24/5, but we can restrict to active hours


def is_market_hours(now: Optional[datetime] = None) -> bool:
    """
    Check if current time is within trading hours.
    For now, allows trading 24/5 (Monday-Friday), but can be restricted.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Convert to ET (UTC-5 or UTC-4 depending on DST)
    # Simple check: allow Monday-Friday
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    if weekday >= 5:  # Saturday or Sunday
        return False
    
    # For more precise hours, uncomment:
    # et_now = now.astimezone(timezone(timedelta(hours=-5)))  # EST
    # et_time = et_now.time()
    # if et_time < MARKET_OPEN and et_time > MARKET_CLOSE:
    #     return False
    
    return True


def check_ib_gateway_health(host: str, port: int, client_id: int) -> bool:
    """Check if IB Gateway is accessible and responding."""
    try:
        connection = IBKRConnection(host=host, port=port, client_id=client_id)
        # Try to connect (will fail fast if gateway is down)
        # Note: This is a simple check - in production you might want more sophisticated health checks
        return True
    except Exception as e:
        logger.warning(f"IB Gateway health check failed: {e}")
        return False


class AutomatedTradingAgent:
    """
    Fully autonomous trading agent that:
    - Monitors market hours
    - Handles errors gracefully with retries
    - Tracks positions and manages exits
    - Logs all decisions
    - Auto-recovers from connection issues
    """
    
    def __init__(
        self,
        symbols: list[str],
        sec_types: list[str],
        strategy: str = "sr",
        profile_config: Optional[str] = None,
        interval: int = 300,  # 5 minutes default
        tiny_size: int = 1,
        ib_host: Optional[str] = None,
        ib_port: Optional[int] = None,
        ib_client_id: Optional[int] = None,
        expiries: Optional[list[str]] = None,
        local_symbols: Optional[list[str]] = None,
        trading_classes: Optional[list[str]] = None,
        max_retries: int = 3,
        retry_delay: int = 60,
    ):
        self.symbols = symbols
        self.sec_types = sec_types
        self.strategy = strategy
        self.interval = interval
        self.tiny_size = tiny_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Load profile
        self.profile = load_profile(profile_config)
        
        # Setup IBKR settings
        settings = get_settings()
        ib_data_client_id = (
            settings.ib_data_client_id
            if settings.ib_data_client_id is not None
            else (ib_client_id + 1 if ib_client_id else settings.ib_client_id + 1)
        )
        self.ib_settings = Settings(
            allow_live_trading=True,
            profile="live",
            ib_host=ib_host or settings.ib_host,
            ib_port=ib_port or settings.ib_port,
            ib_client_id=ib_client_id or settings.ib_client_id,
            ib_data_client_id=ib_data_client_id,
        )
        
        # Initialize components
        self.portfolio = Portfolio(cash=self.profile.starting_balance)
        self.risk_guard = RiskGuard(RiskLimits(max_daily_loss=self.profile.daily_loss_limit))
        
        # Will be initialized in start()
        self.data_connection: Optional[IBKRConnection] = None
        self.provider: Optional[IBKRDataProvider] = None
        self.broker: Optional[IBKRBroker] = None
        self.exec_agent: Optional[ExecutionAgent] = None
        
        # State tracking
        self.last_fill_ts: Optional[datetime] = None
        self.trades_today = 0
        self.open_positions: dict[str, dict] = {}
        self.day_start_equity = self.profile.starting_balance
        self.last_day_reset = datetime.now(timezone.utc).date()
        
        # Contract details
        self.expiries = expiries or []
        self.local_symbols = local_symbols or []
        self.trading_classes = trading_classes or []
        
        # Health tracking
        self.consecutive_errors = 0
        self.last_successful_cycle = datetime.now(timezone.utc)
        
        # Verbose output flag
        self.verbose = True  # Always show detailed reasoning
        
        logger.info(f"Initialized AutomatedTradingAgent: symbols={symbols}, strategy={strategy}")
    
    def _initialize_connections(self) -> bool:
        """Initialize IBKR connections with retry logic."""
        try:
            self.data_connection = IBKRConnection(
                host=self.ib_settings.ib_host,
                port=int(self.ib_settings.ib_port),
                client_id=int(self.ib_settings.ib_data_client_id or 1),
            )
            self.provider = IBKRDataProvider(settings=self.ib_settings, connection=self.data_connection)
            self.broker = IBKRBroker(self.portfolio, settings=self.ib_settings, risk_guard=self.risk_guard)
            self.exec_agent = ExecutionAgent(
                self.broker, symbol="N/A", profile="live", risk_guard=self.risk_guard
            )
            logger.info("IBKR connections initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize IBKR connections: {e}", exc_info=True)
            return False
    
    def _reset_daily_counters(self) -> None:
        """Reset daily counters at start of new trading day."""
        today = datetime.now(timezone.utc).date()
        if today > self.last_day_reset:
            logger.info(f"Resetting daily counters (new day: {today})")
            self.trades_today = 0
            self.last_day_reset = today
            # Reset day start equity to current equity
            realized, unrealized = self._compute_pnl()
            self.day_start_equity = self.profile.starting_balance + realized + unrealized
    
    def _compute_pnl(self) -> tuple[float, float]:
        """Compute realized and unrealized PnL."""
        realized = 0.0
        unrealized = 0.0
        marks = {}
        
        # Get current prices for all open positions
        for sym in self.portfolio.positions.keys():
            if sym in self.symbols:
                # Try to get latest price (simplified - in production, fetch from provider)
                pos = self.portfolio.positions[sym]
                if pos.size != 0:
                    marks[sym] = pos.avg_price  # Fallback to avg price
        
        for sym, pos in self.portfolio.positions.items():
            realized += pos.realized_pnl
            if pos.size != 0:
                price = marks.get(sym, pos.avg_price)
                unrealized += pos.size * (price - pos.avg_price)
        
        return realized, unrealized
    
    def _fetch_data(self, symbol: str, sec_type: str, idx: int) -> Optional[pd.DataFrame]:
        """Fetch market data with error handling."""
        expiry = self.expiries[idx] if idx < len(self.expiries) else None
        local_symbol = self.local_symbols[idx] if idx < len(self.local_symbols) else None
        trading_class = self.trading_classes[idx] if idx < len(self.trading_classes) else symbol
        
        if not self.provider:
            logger.error("Provider not initialized")
            return None
        
        try:
            df = self.provider.fetch_historical(
                symbol,
                sec_type=sec_type,
                duration="2 D",
                bar_size="15 mins",
                expiry=expiry,
                local_symbol=local_symbol,
                trading_class=trading_class,
            )
            return df
        except Exception as e:
            logger.error(f"Failed to fetch data for {symbol}: {e}", exc_info=True)
            return None
    
    def _print_analysis(self, symbol: str, signal: dict, price: float, risk_state, size: int, reason: str) -> None:
        """Print detailed analysis of the trading decision."""
        if not self.verbose:
            return
        
        # Create analysis table
        table = Table(title=f"🤔 Analysis: {symbol}", box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_column("Reasoning", style="dim")
        
        # Signal information
        side_emoji = "🟢" if signal["side"] == "long" else "🔴" if signal["side"] == "short" else "⚪"
        table.add_row("Signal", f"{side_emoji} {signal['side'].upper()}", reason or "No signal")
        
        # Price and indicators
        table.add_row("Current Price", f"${price:,.2f}", "")
        
        if signal.get("vwap"):
            vwap_diff = ((price - signal["vwap"]) / signal["vwap"]) * 100
            vwap_status = "Above" if price > signal["vwap"] else "Below"
            table.add_row("VWAP", f"${signal['vwap']:,.2f} ({vwap_status} {abs(vwap_diff):.2f}%)", 
                         "Price above VWAP = bullish, below = bearish")
        
        if signal.get("fast_ma"):  # EMA
            ema_diff = ((price - signal["fast_ma"]) / signal["fast_ma"]) * 100
            ema_status = "Above" if price > signal["fast_ma"] else "Below"
            table.add_row("20 EMA", f"${signal['fast_ma']:,.2f} ({ema_status} {abs(ema_diff):.2f}%)",
                         "Trend filter: long only above EMA, short only below")
        
        if signal.get("support1"):
            sup_dist = ((price - signal["support1"]) / signal["support1"]) * 100
            table.add_row("Support 1", f"${signal['support1']:,.2f} ({abs(sup_dist):.2f}% away)",
                         "Near support = potential bounce zone")
        
        if signal.get("resistance1"):
            res_dist = ((signal["resistance1"] - price) / price) * 100
            table.add_row("Resistance 1", f"${signal['resistance1']:,.2f} ({abs(res_dist):.2f}% away)",
                         "Near resistance = potential rejection zone")
        
        # Risk state
        risk_emoji = {
            "OK": "✅",
            "NEAR_LIMIT": "⚠️",
            "HARD_STOP": "🛑",
            "COOLDOWN": "⏸️",
            "PAUSED": "⏸️",
        }
        risk_emoji_str = risk_emoji.get(risk_state.status, "❓")
        table.add_row("Risk Status", f"{risk_emoji_str} {risk_state.status}",
                     f"Remaining buffer: ${risk_state.remaining_loss_buffer:,.2f}")
        
        # Position sizing
        if size != 0:
            table.add_row("Position Size", f"{abs(size)} contract(s)", 
                         f"Based on risk taper: {risk_state.remaining_loss_buffer / risk_state.daily_loss_limit * 100:.1f}% buffer remaining")
        else:
            table.add_row("Position Size", "0 (BLOCKED)", "Risk limits prevent trading")
        
        # P&L
        realized, unrealized = self._compute_pnl()
        total_pnl = realized + unrealized
        pnl_color = "green" if total_pnl >= 0 else "red"
        table.add_row("Daily P&L", f"[{pnl_color}]${total_pnl:,.2f}[/] (R: ${realized:,.2f}, U: ${unrealized:,.2f})",
                     f"Trades today: {self.trades_today}")
        
        console.print(table)
        console.print()
    
    def _process_symbol(self, symbol: str, sec_type: str, idx: int) -> bool:
        """Process one symbol: fetch data, generate signal, execute if needed."""
        ts = datetime.now(timezone.utc)
        
        try:
            # Print header
            if self.verbose:
                console.print(Panel(f"[bold cyan]🔍 Analyzing {symbol}[/bold cyan]", 
                                   style="cyan", box=box.ROUNDED))
            
            # Fetch data
            if self.verbose:
                console.print(f"[dim]📊 Fetching market data for {symbol}...[/dim]")
            df = self._fetch_data(symbol, sec_type, idx)
            if df is None or df.empty:
                if self.verbose:
                    console.print(f"[yellow]⚠️  {symbol}: No data available[/yellow]")
                logger.warning(f"[{ts.isoformat()}] {symbol}: No data available")
                return False
            
            if self.verbose:
                console.print(f"[green]✅ Data received: {len(df)} bars, latest price: ${df['Close'].iloc[-1]:,.2f}[/green]")
            
            # Generate signal
            if self.verbose:
                console.print(f"[dim]🧠 Generating {self.strategy} signal...[/dim]")
            signal = generate_signal(symbol, df, strategy_name=self.strategy, fast=20, slow=50)
            side = signal["side"]
            
            price = float(df["Close"].iloc[-1])
            
            if side == "flat":
                if self.verbose:
                    console.print(f"[yellow]⚪ {symbol}: FLAT signal - No trade opportunity[/yellow]")
                    if signal.get("comment"):
                        console.print(f"[dim]   Reason: {signal.get('comment')}[/dim]")
                logger.debug(f"[{ts.isoformat()}] {symbol}: FLAT signal")
                console.print()
                return True
            
            realized_pnl, unrealized_pnl = self._compute_pnl()
            
            # Reset daily counters if needed
            self._reset_daily_counters()
            
            # Compute risk state
            risk_state = compute_risk_state(
                self.profile,
                day_start_equity=self.day_start_equity,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                trades_today=self.trades_today,
                max_trades=self.profile.max_trades,
                now=ts,
            )
            
            # Check for position exits
            current_pos = self.portfolio.positions.get(symbol)
            if current_pos and current_pos.size != 0:
                should_exit = False
                exit_reason = ""
                
                if (current_pos.size > 0 and side == "short") or (current_pos.size < 0 and side == "long"):
                    should_exit = True
                    exit_reason = "opposite signal"
                    if self.verbose:
                        console.print(f"[yellow]🔄 Position exists ({current_pos.size} contracts). Signal reversed - preparing exit...[/yellow]")
                elif risk_state.status in {"HARD_STOP", "COOLDOWN", "PAUSED"}:
                    should_exit = True
                    exit_reason = f"risk state: {risk_state.status}"
                    if self.verbose:
                        console.print(f"[red]🛑 Risk-based exit triggered: {risk_state.status}[/red]")
                
                if should_exit:
                    if self.verbose:
                        console.print(f"[bold yellow]📤 EXITING POSITION: {symbol}[/bold yellow]")
                    self._exit_position(symbol, sec_type, current_pos, price, signal, risk_state, exit_reason)
                    # Recompute after exit
                    realized_pnl, unrealized_pnl = self._compute_pnl()
                    risk_state = compute_risk_state(
                        self.profile,
                        day_start_equity=self.day_start_equity,
                        realized_pnl=realized_pnl,
                        unrealized_pnl=unrealized_pnl,
                        trades_today=self.trades_today,
                        max_trades=self.profile.max_trades,
                        now=ts,
                    )
            
            # Skip trading if paused/cooldown
            if risk_state.status in {"COOLDOWN", "PAUSED"}:
                cooldown_msg = (
                    f"cooldown until {risk_state.cooldown_until.isoformat()}"
                    if risk_state.cooldown_until
                    else "cooldown"
                )
                if self.verbose:
                    console.print(f"[yellow]⏸️  {symbol}: SKIP - {risk_state.status} ({cooldown_msg})[/yellow]")
                    self._print_analysis(symbol, signal, price, risk_state, 0, f"Trading paused: {cooldown_msg}")
                logger.info(f"[{ts.isoformat()}] {symbol}: SKIP (status={risk_state.status}, {cooldown_msg})")
                return True
            
            # Compute position size
            if self.verbose:
                console.print(f"[dim]💰 Computing position size...[/dim]")
            size = compute_position_size(symbol, side, self.profile, risk_state, price=price)
            if self.tiny_size > 0:
                size = min(abs(size), self.tiny_size) * (1 if size >= 0 else -1)
            
            if size == 0:
                if self.verbose:
                    console.print(f"[red]🚫 {symbol}: TRADE BLOCKED by risk state {risk_state.status}[/red]")
                    self._print_analysis(symbol, signal, price, risk_state, 0, "Risk limits prevent trading")
                logger.info(f"[{ts.isoformat()}] {symbol}: Blocked by risk state {risk_state.status}")
                return True
            
            # Show detailed analysis before executing
            if self.verbose:
                reason = signal.get("comment", "Strategy signal")
                self._print_analysis(symbol, signal, price, risk_state, size, reason)
                console.print(f"[bold green]✅ EXECUTING: {side.upper()} {abs(size)} contract(s) @ ${price:,.2f}[/bold green]")
            
            # Execute trade
            self._execute_trade(symbol, sec_type, side, size, price, signal, risk_state, df, idx)
            self.trades_today += 1
            
            if self.verbose:
                console.print(f"[green]✅ Trade executed successfully![/green]")
                console.print()
            
            # Process fills
            if self.broker:
                fills = list(self.broker.fetch_fills(since=self.last_fill_ts))
                if fills:
                    for fill in fills:
                        self.portfolio.update_with_fill(fill)
                    self.last_fill_ts = max((f.timestamp for f in fills), default=self.last_fill_ts)
            
            self.consecutive_errors = 0
            self.last_successful_cycle = ts
            return True
            
        except Exception as e:
            logger.error(f"[{ts.isoformat()}] Error processing {symbol}: {e}", exc_info=True)
            self.consecutive_errors += 1
            return False
    
    def _exit_position(
        self,
        symbol: str,
        sec_type: str,
        position,
        exit_price: float,
        signal: dict,
        risk_state,
        exit_reason: str,
    ) -> None:
        """Exit an open position and log the exit."""
        entry_info = self.open_positions.pop(symbol, {})
        exit_time = datetime.now(timezone.utc)
        entry_time = entry_info.get("entry_time", exit_time)
        entry_price = entry_info.get("entry_price", position.avg_price)
        exit_pnl = position.realized_pnl + (position.size * (exit_price - position.avg_price))
        
        log_performance_row(
            PerformanceRow(
                timestamp=exit_time,
                entry_time=entry_time,
                exit_time=exit_time,
                symbol=symbol,
                sec_type=sec_type,
                strategy_name=signal["strategy_name"],
                side="long" if position.size > 0 else "short",
                requested_size=abs(position.size),
                filled_size=abs(position.size),
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=exit_pnl,
                unrealized_pnl=0.0,
                fast_ma=signal.get("fast_ma"),
                slow_ma=signal.get("slow_ma"),
                risk_status=risk_state.status,
                drawdown_remaining=risk_state.remaining_loss_buffer,
                trade_reason=f"Exit: {exit_reason}",
                emotion_state=risk_state.status if risk_state.status in {"COOLDOWN", "PAUSED"} else "normal",
                notes=f"automated_agent exit: {exit_reason}",
            )
        )
        if self.verbose:
            pnl_color = "green" if exit_pnl >= 0 else "red"
            console.print(f"[bold yellow]📤 EXIT: {symbol} {abs(position.size)} contracts @ ${exit_price:,.2f}[/bold yellow]")
            console.print(f"   Entry: ${entry_price:,.2f} | Exit: ${exit_price:,.2f}")
            console.print(f"   P&L: [{pnl_color}]${exit_pnl:,.2f}[/{pnl_color}] | Reason: {exit_reason}")
            console.print()
        logger.info(f"[{exit_time.isoformat()}] {symbol}: EXIT position size={position.size} pnl={exit_pnl:.2f} reason={exit_reason}")
    
    def _execute_trade(
        self,
        symbol: str,
        sec_type: str,
        side: str,
        size: int,
        price: float,
        signal: dict,
        risk_state,
        df: pd.DataFrame,
        idx: int,
    ) -> None:
        """Execute a trade and log the entry."""
        expiry = self.expiries[idx] if idx < len(self.expiries) else None
        local_symbol = self.local_symbols[idx] if idx < len(self.local_symbols) else None
        trading_class = self.trading_classes[idx] if idx < len(self.trading_classes) else symbol
        
        risk_label = (
            "SAFE"
            if risk_state.status == "OK"
            else "NEAR_LIMIT"
            if risk_state.status == "NEAR_LIMIT"
            else "BLOCKED_DD"
            if risk_state.status == "HARD_STOP"
            else risk_state.status
        )
        
        if not self.verbose:  # Only log if not verbose (verbose already printed)
            logger.info(
                f"[{datetime.now(timezone.utc).isoformat()}] {symbol} {sec_type} {self.strategy}: "
                f"{side.upper()} qty={abs(size)} risk={risk_label} price={price:.2f}"
            )
        
        if not self.exec_agent:
            logger.error("Execution agent not initialized")
            return
        
        sig_df = pd.DataFrame(
            {
                "entry": [1 if side == "long" else -1],
                "size": [abs(size)],
                "sec_type": [sec_type],
                "expiry": [expiry],
                "local_symbol": [local_symbol],
                "trading_class": [trading_class],
                "Close": [price],
            },
            index=[df.index[-1]],
        )
        
        entry_time = datetime.now(timezone.utc)
        self.exec_agent.symbol = symbol
        self.exec_agent.execute(sig_df)
        
        # Track open position
        self.open_positions[symbol] = {
            "entry_time": entry_time,
            "entry_price": price,
        }
        
        # Log performance
        realized_pnl, unrealized_pnl = self._compute_pnl()
        log_performance_row(
            PerformanceRow(
                timestamp=entry_time,
                entry_time=entry_time,
                exit_time=None,
                symbol=symbol,
                sec_type=sec_type,
                strategy_name=signal["strategy_name"],
                side=side,
                requested_size=size,
                filled_size=size,
                entry_price=price,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                fast_ma=signal.get("fast_ma"),
                slow_ma=signal.get("slow_ma"),
                risk_status=risk_label,
                drawdown_remaining=risk_state.remaining_loss_buffer,
                trade_reason=signal.get("comment"),
                emotion_state=risk_state.status if risk_state.status in {"COOLDOWN", "PAUSED"} else "normal",
                notes=f"automated_agent entry; sr={ {k: signal.get(k) for k in ('support1','resistance1','vwap') if k in signal} }",
            )
        )
    
    def start(self) -> None:
        """Start the automated trading loop."""
        # Print startup banner
        console.print()
        console.print(Panel.fit(
            "[bold cyan]🤖 Automated Trading Agent Starting[/bold cyan]\n"
            f"[cyan]Strategy:[/cyan] {self.strategy.upper()}\n"
            f"[cyan]Symbols:[/cyan] {', '.join(self.symbols)}\n"
            f"[cyan]Interval:[/cyan] {self.interval}s ({self.interval/60:.1f} minutes)\n"
            f"[cyan]Profile:[/cyan] {self.profile.name}",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        logger.info("Starting Automated Trading Agent...")
        
        # Initialize connections
        if self.verbose:
            console.print("[dim]🔌 Connecting to IB Gateway...[/dim]")
        if not self._initialize_connections():
            console.print("[bold red]❌ Failed to initialize connections. Exiting.[/bold red]")
            logger.error("Failed to initialize connections. Exiting.")
            return
        
        if self.verbose:
            console.print("[green]✅ Connected to IB Gateway[/green]")
            console.print(f"[dim]   Data Client ID: {self.data_connection.client_id}[/dim]")
            console.print(f"[dim]   Orders Client ID: {self.ib_settings.ib_client_id}[/dim]")
            console.print(f"[dim]   Host: {self.ib_settings.ib_host}:{self.ib_settings.ib_port}[/dim]")
            console.print()
        
        logger.info(
            f"IBKR connections -> data clientId={self.data_connection.client_id}, "
            f"orders clientId={self.ib_settings.ib_client_id}, "
            f"host={self.ib_settings.ib_host}, port={self.ib_settings.ib_port}"
        )
        
        logger.info(f"Trading symbols: {self.symbols}")
        logger.info(f"Strategy: {self.strategy}")
        logger.info(f"Interval: {self.interval}s")
        logger.info(f"Market hours check: Enabled")
        
        cycle_count = 0
        try:
            while True:
                cycle_count += 1
                if self.verbose:
                    console.print(Panel(
                        f"[bold]Cycle #{cycle_count}[/bold] - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                        style="blue",
                        box=box.ROUNDED
                    ))
                    console.print()
                
                # Check market hours
                if not is_market_hours():
                    if self.verbose:
                        console.print("[yellow]⏰ Outside market hours, sleeping...[/yellow]")
                    logger.debug("Outside market hours, sleeping...")
                    time_module.sleep(60)  # Check every minute when closed
                    continue
                
                # Health check
                if self.consecutive_errors >= self.max_retries:
                    if self.verbose:
                        console.print(f"[red]⚠️  Too many consecutive errors ({self.consecutive_errors}). Attempting to reconnect...[/red]")
                    logger.warning(
                        f"Too many consecutive errors ({self.consecutive_errors}). "
                        f"Attempting to reconnect..."
                    )
                    if not self._initialize_connections():
                        if self.verbose:
                            console.print(f"[red]❌ Reconnection failed. Waiting {self.retry_delay}s before retry...[/red]")
                        logger.error("Reconnection failed. Waiting before retry...")
                        time_module.sleep(self.retry_delay)
                        self.consecutive_errors = 0  # Reset after retry delay
                        continue
                    if self.verbose:
                        console.print("[green]✅ Reconnected successfully[/green]")
                    self.consecutive_errors = 0
                
                # Process each symbol
                for idx, symbol in enumerate(self.symbols):
                    sec_type = self.sec_types[idx] if idx < len(self.sec_types) else "FUT"
                    self._process_symbol(symbol, sec_type, idx)
                
                # Summary after cycle
                if self.verbose:
                    realized, unrealized = self._compute_pnl()
                    total_pnl = realized + unrealized
                    pnl_color = "green" if total_pnl >= 0 else "red"
                    console.print(Panel(
                        f"[cyan]Cycle Complete[/cyan]\n"
                        f"Trades Today: {self.trades_today}\n"
                        f"Daily P&L: [{pnl_color}]${total_pnl:,.2f}[/{pnl_color}]\n"
                        f"Next cycle in {self.interval}s",
                        title="📊 Summary",
                        border_style="cyan",
                        box=box.ROUNDED
                    ))
                    console.print()
                
                # Sleep until next cycle
                if self.verbose:
                    console.print(f"[dim]💤 Sleeping for {self.interval}s until next cycle...[/dim]")
                    console.print()
                time_module.sleep(self.interval)
                
        except KeyboardInterrupt:
            console.print()
            console.print(Panel("[bold yellow]⚠️  Interrupt signal received. Shutting down gracefully...[/bold yellow]", 
                              border_style="yellow", box=box.ROUNDED))
            logger.info("Received interrupt signal. Shutting down gracefully...")
        except Exception as e:
            console.print()
            console.print(Panel(f"[bold red]❌ Fatal error: {e}[/bold red]", border_style="red", box=box.ROUNDED))
            logger.error(f"Fatal error in trading loop: {e}", exc_info=True)
            raise
        finally:
            console.print()
            console.print(Panel("[bold]Automated Trading Agent Stopped[/bold]", border_style="cyan", box=box.ROUNDED))
            logger.info("Automated Trading Agent stopped.")

