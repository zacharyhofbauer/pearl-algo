# NQ Agent Diagnostic Report
**Date:** December 16, 2025  
**Issue:** Agent stopped working last night and no trades were called

## Root Cause Analysis

### Primary Issue: IB Gateway Connection Lost

The agent stopped generating signals because **IB Gateway is not running**. The agent process is still active but cannot fetch market data, which prevents signal generation.

### Evidence

1. **IB Gateway Status:** Not running
   - No Java process found for IB Gateway/IBC
   - Port 4002 not listening

2. **Agent Process:** Still running but degraded
   - PID: 18052
   - Started: Dec 15, 18:45 UTC (1:45 PM ET)
   - Uptime: ~17 hours
   - Status: Running but unable to fetch data

3. **Error Logs:** Connection refused errors
   ```
   ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 4002)
   Not connected to IB Gateway
   No latest bar available for NQ
   ```

4. **State File:** Last update at 00:25:54 UTC (Dec 16)
   - Matches screenshot showing last Telegram message at 7:20 PM ET (Dec 15)
   - 320 cycles completed
   - 0 signals generated
   - Buffer size: 77 bars (stale data)

### Why No Trades Were Called

1. **No Market Data:** Agent cannot connect to IB Gateway to fetch real-time data
2. **No Signals:** Without data, the signal generator cannot analyze market conditions
3. **Silent Failure:** Agent continued running but didn't alert about the connection issue

## Fixes Implemented

### 1. Enhanced Connection Error Detection
- Added `_is_connection_error()` method to distinguish connection failures from normal market closure
- Checks executor connection status before assuming data is just empty
- Tracks connection failures separately from general data fetch errors

### 2. Improved Alerting
- Sends Telegram alerts when IB Gateway connection is lost
- Alerts include actionable suggestions (check gateway status, restart gateway)
- Throttled alerts (every 10 minutes) to avoid spam

### 3. Circuit Breaker for Connection Failures
- After 10 consecutive connection failures, agent pauses itself
- Sends critical alert: "IB Gateway connection lost - Service paused"
- Prevents agent from wasting resources when gateway is down

### 4. Enhanced Status Reporting
- Status updates now include connection status (connected/disconnected)
- Shows connection failure count
- Better visibility into agent health

## Immediate Actions Required

### 1. Restart IB Gateway
```bash
cd /home/pearlalgo/pearlalgo-dev-ai-agents
./scripts/start_ibgateway_ibc.sh
```

### 2. Verify Gateway is Running
```bash
./scripts/check_gateway_status.sh
# OR
pgrep -f "java.*IBC\|ibgateway"
netstat -tlnp | grep 4002  # Should show port 4002 listening
```

### 3. Restart NQ Agent (if needed)
```bash
# Stop current agent
./scripts/stop_nq_agent_service.sh

# Start fresh
./scripts/start_nq_agent_service.sh
```

### 4. Monitor Recovery
```bash
# Watch logs
tail -f logs/nq_agent.log

# Check status
./scripts/check_nq_agent_status.sh
```

## Prevention Measures

### 1. Automated Gateway Monitoring
Consider adding a systemd service or cron job to:
- Monitor IB Gateway process
- Auto-restart if it crashes
- Alert if gateway is down for extended periods

### 2. Health Check Script
Create a monitoring script that:
- Checks IB Gateway status
- Checks agent status
- Sends alerts if either is down
- Can be run via cron every 5-10 minutes

### 3. Service Dependencies
Consider using systemd service dependencies so:
- Agent service depends on IB Gateway service
- Agent won't start if gateway isn't available
- Systemd can auto-restart both services

## Code Changes Summary

### Modified Files
1. `src/pearlalgo/nq_agent/service.py`
   - Added connection failure tracking
   - Enhanced error detection for connection issues
   - Added circuit breaker for extended connection failures
   - Improved status reporting with connection status

2. `src/pearlalgo/nq_agent/telegram_notifier.py`
   - Enhanced status messages to show connection status
   - Better alerts for connection failures

## Testing Recommendations

1. **Test Connection Failure Detection:**
   - Stop IB Gateway while agent is running
   - Verify agent detects connection loss within 1-2 cycles
   - Verify Telegram alerts are sent

2. **Test Circuit Breaker:**
   - Keep gateway down for 10+ cycles
   - Verify agent pauses itself
   - Verify critical alert is sent

3. **Test Recovery:**
   - Restart IB Gateway
   - Verify agent resumes automatically (if not paused)
   - Verify data fetching resumes

## Next Steps

1. ✅ Diagnose root cause
2. ✅ Implement connection error detection
3. ✅ Add improved alerting
4. ✅ Add circuit breaker
5. ⏳ Restart IB Gateway
6. ⏳ Verify agent recovery
7. ⏳ Set up monitoring/automation (optional)

---

**Note:** The agent will now automatically detect and alert when IB Gateway is down, preventing silent failures like this in the future.
