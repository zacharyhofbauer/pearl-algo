# Pearl AI Knowledge Base

This document captures learned patterns, preferences, and solutions for the Pearl trading system.

## User Preferences

### Trading Configuration
- **Virtual PnL**: Always keep enabled for paper trading validation
- **All Sessions**: User prefers all trading sessions enabled (overnight, premarket, morning, midday, afternoon, close)
- **Direction Gating**: Usually disabled - allow both long and short trades regardless of regime
- **Skip Overnight**: Keep disabled - trade overnight session
- **Mode**: Use `warn_only` for circuit breaker - log but don't block

### When User Says "Open to All Trades"
This means:
1. Set `skip_overnight: false`
2. Enable all sessions in `allowed_sessions`
3. Disable `direction_gating`
4. Keep circuit breaker in `warn_only` mode

## Web App Customization

### Mobile Optimization Principles
- Never hide data, just reorganize and make more compact
- Use smaller fonts and tighter padding on mobile
- Grids should be responsive (3-col desktop, 2-col mobile)
- Chart info bar: single row with price, countdown, legend
- Legend colors must match actual chart indicators

### Chart Info Bar Pattern
Format: `[Price] | [Countdown Dot + TF + Time] | [Legend]`
- Price: mono font, green/red based on direction
- Countdown: live dot + timeframe label + remaining time
- Legend: colored lines for EMAs, markers for trades

### Legend Colors (Must Match Chart)
- EMA9: `#00d4ff` (cyan)
- EMA21: `#ffc107` (yellow)
- VWAP: `#2962ff` (blue)
- Entry markers: `rgba(180, 180, 180, 0.9)` (gray)
- Win exit: `rgba(100, 200, 180, 0.9)` (teal)
- Loss exit: `rgba(220, 140, 100, 0.9)` (orange)

### Pearl AI Panel
- Should stand out with purple gradient border
- Is becoming increasingly important - prioritize visibility
- Show AI status pills (Bandit, Contextual, ML modes)
- Shadow impact metrics in responsive grid

**Note**: AI chat features have been removed from Telegram. For AI-powered analysis and assistance, use the CLI/terminal interface or the web app Pearl AI panel instead.

## Troubleshooting

### Agent Not Running/Stale Data
1. Check process: `ps aux | grep market_agent`
2. Check logs: `tail -50 logs/agent_NQ.log`
3. Restart: `pkill -f "market_agent.main" && source .venv/bin/activate && nohup python -m pearlalgo.market_agent.main > logs/agent_NQ.log 2>&1 &`

### IBKR Gateway Issues
1. Check gateway: `ps aux | grep -i ibc`
2. Look for "Read-Only mode" or connection errors in logs
3. Gateway is in paper trading mode (DUK947427 account)

### Config YAML Errors
- Watch for missing newlines between sections
- Common error: values running into next section name
- Example fix: `temperature: 0.7ai_briefings:` should be two lines

### Web App Not Updating
1. Build: `npm run build`
2. Kill old: `pkill -f "next-server"`
3. Start: `nohup npm start -- -p 3001 > /tmp/next-server.log 2>&1 &`
4. Verify: `curl -s -o /dev/null -w "%{http_code}" http://localhost:3001`

## Common Tasks

### Restart Agent with Fresh Config
```bash
pkill -f "market_agent.main"
sleep 2
source .venv/bin/activate
nohup python -m pearlalgo.market_agent.main > logs/agent_NQ.log 2>&1 &
```

### Check Trading Status
```bash
python3 -c "
import json
with open('data/agent_state/NQ/state.json') as f:
    d = json.load(f)
print('Running:', d.get('running'))
print('Data fresh:', d.get('data_fresh'))
print('Active trades:', d.get('active_trades_count'))
"
```

### Verify Config Settings
```bash
python3 -c "
import yaml
with open('config/config.yaml') as f:
    cfg = yaml.safe_load(f)
print('Virtual PnL:', cfg['virtual_pnl']['enabled'])
print('Skip overnight:', cfg['signals']['skip_overnight'])
print('Direction gating:', cfg['trading_circuit_breaker']['enable_direction_gating'])
"
```

## Session Times (ET)
- Overnight: 6PM - 4AM
- Premarket: 4AM - 6AM
- Morning: 6AM - 10AM
- Midday: 10AM - 2PM
- Afternoon: 2PM - 5PM
- Close: 5PM - 6PM

## Git Workflow
- Commit messages should be descriptive
- Always include `Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>`
- Push requires remote configured
