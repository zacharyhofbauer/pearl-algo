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
- WebSocket streaming (Bybit/Binance) with automatic reconnection
- IBKR REST API (futures)
- Polygon.io (fallback)

**Features**:
- Automatic reconnection with exponential backoff
- Data normalization to consistent format (timestamp, symbol, price, volume)
- Both synchronous and asynchronous interfaces
- Data buffering for historical context

**Output**: `MarketData` objects in shared state

### 2. Quant Research Agent
**Responsibility**: Generate trading signals

**Capabilities**:
- Technical analysis (momentum, mean-reversion, breakout)
- Modular strategy selection (configurable per symbol)
- Regime detection (trending vs ranging)
- ML model support (placeholder for sklearn/vectorbt integration)
- LLM reasoning (Groq/LiteLLM) for signal explanation with retry logic
- Confidence scoring

**Features**:
- Strategy parameters from config (per-symbol overrides)
- ML feature extraction for future model integration
- Circuit breaker protection for LLM calls
- Retry logic with exponential backoff

**Output**: `Signal` objects in shared state with all required fields (symbol, direction, entry, stop, target, confidence, rationale)

### 3. Risk Manager Agent
**Responsibility**: Evaluate risk and calculate position sizes

**Enforced Rules** (Configurable, defaults to safe values):
- Max 2% risk per trade (configurable, defaults to 2%)
- 15% account drawdown kill-switch (hardcoded for safety)
- No martingale (hardcoded)
- No averaging down (hardcoded)
- Volatility targeting (0.5-1% daily vol, ATR-based)
- Cool-down periods after max trades or stopping conditions

**Features**:
- Volatility-targeted position sizing (ATR or realized volatility)
- Configurable risk per trade (with safe defaults)
- Enhanced performance logging (entry/exit times, drawdown, trade reason)

**Output**: `PositionDecision` objects in shared state

### 4. Portfolio/Execution Agent
**Responsibility**: Execute trades and manage positions

**Capabilities**:
- Final decision making (combines signals + risk)
- Order placement via broker abstraction with retry logic
- Position management
- Stop-loss and take-profit orders
- Enhanced performance logging

**Features**:
- Retry logic with exponential backoff for order submission
- Circuit breaker protection for broker API calls
- Comprehensive trade logging (entry/exit times, drawdown remaining, trade reason)
- Automatic performance tracking

**Output**: Executed orders, updated portfolio, performance logs

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

### State Persistence

**File-Based Storage (Default)**:
- State saved to `data/state_cache/state.json`
- Automatic save on workflow completion
- Automatic load on startup
- JSON format for human readability

**Redis Backend (Optional)**:
- Configured via `docker-compose.yml`
- Distributed state for multi-instance deployments
- Automatic fallback to file-based if Redis unavailable

**Migration Path**:
- Schema versioning for state evolution
- Automatic migration on schema changes
- Backward compatibility maintained

**Integration**:
- State loaded before workflow execution
- State saved after each workflow cycle
- Graceful handling of corrupted state files

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

### Docker Deployment (24/7 Operation)

**Multi-Stage Build**:
- Optimized Dockerfile with minimal image size (<500MB)
- Separate build and runtime stages
- Fast startup time

**Docker Compose Services**:
- `trading-bot`: Main trading system with health checks
- `dashboard`: Streamlit dashboard
- `redis`: Optional Redis service for state persistence

**Features**:
- Health checks (`/healthz` endpoint)
- Auto-restart on failures
- State persistence across restarts
- Resource limits and restart policies
- Volume mounts for logs, data, and state

**Deployment Commands**:
```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f trading-bot

# Check health
curl http://localhost:8080/healthz

# Restart (preserves state)
docker-compose restart trading-bot

# Stop
docker-compose down
```

### Cloud Deployment
- Use docker-compose for orchestration
- Health checks ensure 24/7 operation
- Auto-restart on failures
- State persistence for seamless recovery
- Graceful shutdown with signal handling

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
- Structured logging with correlation IDs
- JSON-formatted logs (optional) for log aggregation
- Timing metrics for each agent execution
- Agent reasoning traces
- Performance metrics
- Request tracing with correlation IDs

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

