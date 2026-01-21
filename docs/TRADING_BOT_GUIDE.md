# Trading Bot (AutoBot) Guide

This system runs **one agent per market** (NQ/ES/GC) and **one active trading bot per agent**.

## Runtime model (no confusion)

- **Agent**: one running process for a single market (e.g., NQ).
- **Trading bot (AutoBot)**: the single all-in-one decision engine selected by config.
- **AI advisor (optional)**: observes and suggests; it does not trade.

## Configuration (single trading bot)

Add to `config/config.yaml` (or a per-market config under `config/markets/*.yaml`):

```yaml
trading_bot:
  enabled: true
  selected: "PearlAutoBot"
  available:
    PearlAutoBot:
      class: "PearlAutoBot"
      enabled: true
      parameters: {}
```

Rules:
- Only `selected` is instantiated and evaluated.
- No signal merging across bots.

## Telegram UI

- Use **Markets** to select the active market.
- Use **Bots** to view the **active trading bot** (singular) and performance.

## Backtesting

Backtests remain available as **variants**. Runtime is still one AutoBot per market agent.

