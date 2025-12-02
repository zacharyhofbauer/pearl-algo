# Architecture Overview - LangGraph Multi-Agent Trading System

**Note**: This system uses LangGraph architecture exclusively. Legacy components have been archived. See `MIGRATION_GUIDE.md` for details.

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Workflow                        │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ Market Data   │──▶│ Quant Research│──▶│ Risk Manager  │
│    Agent      │   │    Agent      │   │    Agent      │
└───────────────┘   └───────────────┘   └───────────────┘
        │                   │                   │
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Portfolio/    │
                    │ Execution     │
                    │    Agent      │
                    └───────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Broker     │
                    │  (IBKR/Bybit/ │
                    │    Alpaca)    │
                    └───────────────┘
```

## Component Details

### 1. Market Data Agent
**Responsibility**: Fetch and stream real-time market data

**Data Sources**:
- WebSocket streaming (Bybit/Binance)
- IBKR REST API (futures)
- Polygon.io (fallback)

**Output**: `MarketData` objects in shared state

### 2. Quant Research Agent
**Responsibility**: Generate trading signals

**Capabilities**:
- Technical analysis (momentum, mean-reversion, breakout)
- Regime detection (trending vs ranging)
- LLM reasoning (Groq/LiteLLM) for signal explanation
- Confidence scoring

**Output**: `Signal` objects in shared state

### 3. Risk Manager Agent
**Responsibility**: Evaluate risk and calculate position sizes

**Enforced Rules** (HARDCODED):
- Max 2% risk per trade
- 15% account drawdown kill-switch
- No martingale
- No averaging down
- Volatility targeting (0.5-1% daily vol)

**Output**: `PositionDecision` objects in shared state

### 4. Portfolio/Execution Agent
**Responsibility**: Execute trades and manage positions

**Capabilities**:
- Final decision making (combines signals + risk)
- Order placement via broker abstraction
- Position management
- Stop-loss and take-profit orders

**Output**: Executed orders, updated portfolio

## State Management

### TradingState (Shared State)
- `market_data`: Dict[str, MarketData] - Latest market data per symbol
- `signals`: Dict[str, Signal] - Generated signals per symbol
- `risk_state`: RiskState - Current risk status
- `portfolio`: Portfolio - Portfolio state
- `position_decisions`: Dict[str, PositionDecision] - Approved positions
- `agent_reasoning`: List[AgentReasoning] - Agent logs
- `equity_curve`: List[float] - Historical equity
- `trading_enabled`: bool - Trading flag
- `kill_switch_triggered`: bool - Kill-switch status

## Broker Abstraction

### Unified Interface
All brokers implement the `Broker` interface:
- `submit_order(order: OrderEvent) -> str`
- `fetch_fills(since: datetime) -> Iterable[FillEvent]`
- `cancel_order(order_id: str) -> None`
- `sync_positions() -> Dict[str, float]`

### Supported Brokers
1. **IBKR** - Primary for futures (ES, NQ, CL, GC)
2. **Bybit** - Crypto perpetuals (BTC/USD, ETH/USD)
3. **Alpaca** - US futures (alternative to IBKR)

## Data Flow

1. **Market Data Agent** fetches latest prices → Updates `state.market_data`
2. **Quant Research Agent** analyzes data → Generates `state.signals`
3. **Risk Manager Agent** evaluates risk → Creates `state.position_decisions`
4. **Portfolio/Execution Agent** executes → Updates portfolio and places orders

## Risk Management Flow

```
Current Equity
    │
    ▼
Calculate PnL (realized + unrealized)
    │
    ▼
Check Drawdown vs 15% Limit
    │
    ├─▶ Exceeded → Kill Switch Triggered
    │
    └─▶ OK → Check Risk State
            │
            ├─▶ HARD_STOP/COOLDOWN → Block Trading
            │
            └─▶ OK → Calculate Position Size
                    │
                    ├─▶ Enforce 2% Max Risk
                    │
                    └─▶ Check Averaging Down (blocked)
```

## Configuration

### config/config.yaml
- Broker selection and credentials
- Trading symbols and timeframes
- Strategy parameters
- Risk rules (reference only - hardcoded in code)
- LLM provider settings
- Alert configuration

### Environment Variables (.env)
- API keys (IBKR, Bybit, Alpaca)
- LLM API keys (Groq, OpenAI)
- Alert tokens (Telegram, Discord)

## Deployment

### Local Development
```bash
python -m pearlalgo.live.langgraph_trader --mode paper
```

### Docker Deployment
```bash
docker-compose up -d
```

### Cloud Deployment
- Use docker-compose for orchestration
- Health checks ensure 24/7 operation
- Auto-restart on failures

## Monitoring

### Streamlit Dashboard
- Live equity curve
- Current positions
- Agent reasoning logs
- Risk metrics

### Alerts
- Telegram: Trade notifications, risk warnings
- Discord: Same as Telegram via webhooks

### Logging
- Structured logging with loguru
- Agent reasoning traces
- Performance metrics

## Testing Strategy

1. **Unit Tests**: Each agent tested independently
2. **Integration Tests**: Full workflow tested end-to-end
3. **Backtesting**: Historical data validation
4. **Paper Trading**: Real-time validation without risk

## Safety Features

1. **Hardcoded Risk Rules**: Cannot be overridden without code changes
2. **Kill-Switch**: Automatic stop at 15% drawdown
3. **Paper Trading Default**: Must explicitly enable live trading
4. **Position Limits**: Per-symbol and portfolio-wide limits
5. **Circuit Breakers**: Multiple safety mechanisms

