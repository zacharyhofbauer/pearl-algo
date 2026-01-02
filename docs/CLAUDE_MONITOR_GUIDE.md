# Claude Monitor Guide

> **AI-Powered Monitoring and Assistance for PearlAlgo Trading Agent**

The Claude Monitor is an intelligent assistant that runs alongside your NQ Agent, continuously analyzing performance, detecting issues, and suggesting optimizations. It uses Claude AI to provide context-aware insights and actionable recommendations.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Features](#features)
4. [Telegram Commands](#telegram-commands)
5. [Configuration](#configuration)
6. [Analysis Dimensions](#analysis-dimensions)
7. [Alert System](#alert-system)
8. [Suggestions & Actions](#suggestions--actions)
9. [Reports](#reports)
10. [Troubleshooting](#troubleshooting)

---

## Overview

### What Claude Monitor Does

- **Monitors** signal quality, system health, and market conditions 24/7
- **Detects** issues proactively (win rate degradation, errors, regime changes)
- **Alerts** you via Telegram with intelligent deduplication
- **Suggests** configuration optimizations and code improvements
- **Reports** daily and weekly performance summaries

### Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   NQ Agent      │────▶│  State Files    │◀────│ Claude Monitor  │
│   Service       │     │  (state.json)   │     │    Service      │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                               ┌─────────────────────────┼─────────────────────────┐
                               │                         │                         │
                        ┌──────▼──────┐          ┌──────▼──────┐          ┌───────▼───────┐
                        │   Signal    │          │   System    │          │    Market     │
                        │  Analyzer   │          │  Analyzer   │          │   Analyzer    │
                        └──────┬──────┘          └──────┬──────┘          └───────┬───────┘
                               │                        │                         │
                               └────────────┬───────────┴─────────────────────────┘
                                            │
                                     ┌──────▼──────┐
                                     │   Claude    │
                                     │     API     │
                                     └──────┬──────┘
                                            │
                               ┌────────────┼────────────┐
                               │            │            │
                        ┌──────▼──────┐ ┌───▼────┐ ┌────▼─────┐
                        │   Alerts    │ │Reports │ │Suggestions│
                        │  (Telegram) │ │        │ │           │
                        └─────────────┘ └────────┘ └───────────┘
```

---

## Quick Start

### Prerequisites

1. **Anthropic API Key**: Get from [console.anthropic.com](https://console.anthropic.com/)
2. **LLM Extra Installed**: `pip install -e .[llm]`

### Setup

1. Add your API key to `.env`:
   ```bash
   echo 'ANTHROPIC_API_KEY=sk-ant-api03-...' >> .env
   ```

2. Enable Claude Monitor in `config/config.yaml` (enabled by default):
   ```yaml
   claude_monitor:
     enabled: true
   ```

3. Restart the Telegram command handler:
   ```bash
   pkill -f telegram_command_handler
   ./scripts/telegram/start_command_handler.sh --background
   ```

### Verify Setup

From Telegram:
```
/claude_status
```

You should see:
```
🤖 Claude Monitor Status

🟢 Running: true
✅ Claude API: available
✅ Telegram: configured
```

---

## Features

### Real-Time Monitoring

- Monitors agent state every 60 seconds
- Detects issues within minutes
- Intelligent alert deduplication (no spam)

### Multi-Dimensional Analysis

| Dimension | What It Monitors |
|-----------|-----------------|
| **Signals** | Win rate, R:R ratio, confidence calibration |
| **System** | Errors, connections, data quality |
| **Market** | Regime, volatility, session conditions |
| **Code** | Config drift, technical debt (hourly) |

### Proactive Alerts

- 🔴 **Critical**: Immediate action required
- 🟡 **Warning**: Degradation detected
- 🔵 **Info**: Opportunity identified
- 🟢 **Success**: Improvement confirmed

### Actionable Suggestions

- Configuration tuning recommendations
- Signal type enable/disable suggestions
- Parameter optimization based on backtests

---

## Telegram Commands

### Monitor Status & Control

| Command | Description |
|---------|-------------|
| `/start_monitor` | Start Claude monitor background service (daily reports + proactive alerts) |
| `/stop_monitor` | Stop Claude monitor background service |
| `/monitor_status` | Show monitor service status (alias/quick check) |
| `/claude_status` | Show Claude monitor health & recent insights |
| `/claude_reports` | Configure daily/weekly report settings |

### Analysis Commands

| Command | Description |
|---------|-------------|
| `/analyze_now` | Force immediate comprehensive analysis |
| `/review` | One-tap Strategy Review (runs analysis + shows top recommendations + action buttons) |
| `/analyze_signals` | Deep dive on signal quality |
| `/analyze_system` | System health report |
| `/analyze_market` | Market conditions & regime analysis |

### Suggestions & Actions

| Command | Description |
|---------|-------------|
| `/suggest_config` | Get configuration tuning suggestions |
| `/suggestions` | List all active suggestions |
| `/apply_suggestion <id>` | Apply a suggested change |

### Examples

**Check signal performance:**
```
/analyze_signals
```

Response:
```
🟢 Signal Analysis

Signals Analyzed: 24
Win Rate: 🟢 58.3%
Best Type: sr_bounce
Worst Type: momentum_long

Findings (2):
🟡 Low win rate for momentum_long
🔵 Confidence not predictive

💡 Consider disabling momentum_long
```

**Get config suggestions:**
```
/suggest_config
```

Response:
```
💡 Config Recommendations

*Disable momentum_long*
Path: strategy.disabled_signals
Suggested: [momentum_long]
*Removing consistently losing signal type improves overall performance*
```

---

## Configuration

All configuration is in `config/config.yaml` under `claude_monitor:`.

### Core Settings

```yaml
claude_monitor:
  enabled: true                        # Master toggle
  timezone: "America/New_York"         # Timezone for reports + quiet hours (default: ET)
  
  # Monitoring intervals
  realtime_monitoring: true            # Every 60 seconds
  realtime_interval_seconds: 60
  frequent_interval_seconds: 900       # Full analysis every 15 min
```

### Report Settings

```yaml
claude_monitor:
  # Daily report
  daily_report_enabled: true
  daily_report_time: "09:00"           # Time in claude_monitor.timezone
  
  # Weekly report
  weekly_report_enabled: true
  weekly_report_day: "monday"
  weekly_report_time: "09:00"
```

### Alert Settings

```yaml
claude_monitor:
  # Alert levels to send
  alert_levels:
    - critical
    - warning
    - info
  
  # Deduplication (prevent spam)
  dedup_window_seconds: 900            # 15 minutes
  max_alerts_per_hour: 20
  
  # Quiet hours
  quiet_hours_start: "22:00"           # Time in claude_monitor.timezone
  quiet_hours_end: "07:00"             # Time in claude_monitor.timezone
  suppress_info_during_quiet: true
```

### Suggestion Settings

```yaml
claude_monitor:
  max_suggestions_per_analysis: 5
  auto_apply_enabled: false            # Require manual approval
  max_auto_changes_per_day: 3
```

---

## Analysis Dimensions

### Signal Analysis

Monitors trading signal quality:

- **Win rate by signal type**: Compares to baseline (e.g., sr_bounce: 60%)
- **R:R ratio analysis**: Actual vs expected
- **Confidence calibration**: Do high-confidence signals win more?
- **Duplicate detection**: Prevents repeated signals

**Baselines (default):**

| Signal Type | Expected Win Rate |
|-------------|------------------|
| sr_bounce | 60% |
| mean_reversion_long | 55% |
| mean_reversion_short | 55% |
| momentum_short | 50% |
| breakout_long | 45% |
| breakout_short | 45% |

### System Analysis

Monitors system health:

- **Agent status**: Running, paused, stopped
- **Error patterns**: Consecutive errors, circuit breakers
- **Connection health**: IBKR Gateway status
- **Data quality**: Freshness, buffer fill
- **Telegram delivery**: Send success rate

**Thresholds:**

| Metric | Warning | Critical |
|--------|---------|----------|
| Consecutive errors | 3 | 7 |
| Connection failures | 3 | 7 |
| Data staleness | 5 min | 15 min |
| Telegram failures | 10% | 30% |

### Market Analysis

Monitors market conditions:

- **Regime detection**: Trending (bull/bear), ranging, choppy
- **Volatility level**: High, normal, low
- **Session tracking**: Tokyo, London, New York
- **Trading bias**: Long, short, neutral

---

## Alert System

### How Alerts Work

1. **Analysis runs** (every 60 seconds for real-time, 15 min for full)
2. **Findings extracted** from each dimension
3. **Alerts generated** for significant findings
4. **Deduplication applied** (same alert not repeated within window)
5. **Rate limiting** (max 20/hour)
6. **Quiet hours** honored (INFO suppressed 10pm-7am)

### Alert Escalation

Warnings can escalate to Critical if they persist:

```
Warning: Connection issues (1)
Warning: Connection issues (2)
Warning: Connection issues (3)
🔴 CRITICAL: Connection issues (escalated)
```

### Suppressing Alerts

If an alert is a known issue:
- It will be automatically suppressed after first delivery
- Use the alert fingerprint in code to permanently suppress

---

## Suggestions & Actions

### Suggestion Types

| Type | Description | Auto-apply? |
|------|-------------|-------------|
| `config_change` | Modify config.yaml | No (default) |
| `parameter_tune` | Specific parameter adjustment | No |
| `service_action` | Restart agent/gateway | No |
| `code_patch` | Generate code diff | No |
| `investigation` | Manual investigation needed | N/A |

### Approval Workflow

1. Claude detects issue and generates suggestion
2. Suggestion added to active list
3. You review via `/suggestions` or `/suggest_config`
4. Apply with `/apply_suggestion <id>`
5. Change is made (or dry-run if configured)
6. Audit log records the action

### Safety Features

- **Dry-run mode**: Test changes before applying
- **Rate limiting**: Max N changes per day
- **Automatic backup**: Config backed up before changes
- **Rollback support**: Revert failed changes

---

## Reports

### Daily Report (9am ET)

Includes:
- Agent status summary
- Signal count and types (24h)
- Win rate and P/L
- System health overview
- Monitor stats

### Weekly Report (Monday 9am ET)

Includes:
- 7-day signal summary
- Performance trends
- Applied changes
- Strategic recommendations

### Manual Reports

Force a report anytime:
```
/analyze_now
```

---

## Troubleshooting

### Claude Not Available

```
❌ Claude API: unavailable
```

**Fix:**
1. Check `ANTHROPIC_API_KEY` in `.env`
2. Ensure `pip install -e .[llm]` was run
3. Verify API key at console.anthropic.com

### No Alerts Received

**Check:**
1. Is monitor enabled? (`/claude_status`)
2. Quiet hours active? (10pm-7am suppresses INFO)
3. Rate limit hit? (20/hour)
4. Telegram configured?

### Analysis Taking Too Long

Claude API calls have 180s timeout. If analyses timeout:
1. Check network connectivity
2. Reduce analysis frequency in config
3. API may be experiencing load

### Suggestions Not Generating

Claude needs sufficient data:
- At least 5 signals for signal analysis
- Agent must be running for system analysis
- Market must be open for market analysis

---

## Best Practices

1. **Start with defaults**: The default configuration is tuned for most use cases

2. **Monitor alert volume**: If too many alerts, increase `dedup_window_seconds`

3. **Review suggestions daily**: Don't let the suggestion queue grow too long

4. **Trust but verify**: Always review suggestions before applying

5. **Check daily reports**: Best way to stay informed without constant monitoring

---

## Files Reference

| File | Purpose |
|------|---------|
| `src/pearlalgo/claude_monitor/` | Monitor service code |
| `config/config.yaml` | Configuration (claude_monitor section) |
| `data/nq_agent_state/claude_observations.jsonl` | Analysis history |
| `data/nq_agent_state/claude_suggestions.json` | Active suggestions |
| `data/nq_agent_state/claude_applied_changes.jsonl` | Change audit log |
| `scripts/lifecycle/start_claude_monitor.sh` | Startup script |

---

## API Cost Estimate

Claude Monitor is designed to be cost-efficient:

| Activity | Frequency | Tokens | Monthly Cost |
|----------|-----------|--------|--------------|
| Real-time monitoring | Every 60s | ~100 | ~$2 |
| Frequent analysis | Every 15min | ~2K | ~$5 |
| Hourly code analysis | Every hour | ~5K | ~$3 |
| Daily report | Daily | ~10K | ~$1 |

**Total: ~$10-15/month** with Claude Sonnet 4

---

*Last Updated: 2025-12-30*




