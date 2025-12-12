# Troubleshooting 

## Common Issues and Solutions

### Issue 1: Rate Limiting (429 Errors)

**Symptoms:**
```
Error fetching ... too many 429 error responses
```

**Causes:**
- Too many simultaneous requests
- Both workers starting at the same time
- Burst requests exceeding API limits

**Solutions:**

1. **Wait for rate limit to reset** (usually 1 minute):
   ```bash
   # Wait 60 seconds, then restart
   sleep 60
   python -m pearlalgo.monitoring.continuous_service --config config/config.yaml
   ```

2. **Increase rate limit delay** in `config/config.yaml`:
   ```yaml
   rate_limits:
     
       requests_per_minute: 150  # Reduce from 200
       delay_between_requests: 0.5  # Increase from 0.25
   ```

3. **Disable one worker temporarily** to reduce load:
   ```yaml
   monitoring:
     workers:
       options_intraday:
         enabled: false  # Disable intraday scanner temporarily
   ```

### Issue 2: Invalid Price (Price = 0)

**Symptoms:**
```
WARNING: Invalid price for QQQ: 0
```

**Causes:**
- Market closed (no current data)
- API returning previous day's close as 0
- Data not yet available for today

**Solutions:**

1. **Check if market is open:**
   ```python
   from pearlalgo.utils.market_hours import is_market_open
   print(is_market_open())  # Should be True during market hours
   ```

2. **The system now handles this automatically:**
   - Retries with exponential backoff
   - Validates price > 0 before using
   - Skips symbols with invalid data

3. **If market is closed**, this is expected behavior - the system will wait for market open.

### Issue 3: No Data Returned

**Symptoms:**
```
No price data for SPY
Generated 0 options signals
```

**Solutions:**

1. **Test API directly:**
   ```python
   import asyncio
   from pearlalgo.data_providers.
   import os
   
   async def test():
       provider = .getenv('MASSIVE_API_KEY'))
       data = await provider.get_latest_bar('QQQ')
       print(f"QQQ data: {data}")
       await provider.close()
   
   asyncio.run(test())
   ```

2. **Check API key validity:**
   ```bash
   echo $MASSIVE_API_KEY
   # Should show your API key (not empty)
   ```

3. **Verify symbol format:**
   - Use stock symbols: "QQQ", "SPY" (not options symbols)
   - Ensure symbols are valid tickers

### Issue 4: Circuit Breaker Open

**Symptoms:**
```
Circuit breaker is OPEN, skipping request
```

**Solution:**
- Wait 5 minutes for automatic reset
- Or restart the service:
  ```bash
  sudo systemctl restart pearlalgo-continuous-service.service
  ```

## Quick Fixes

### Immediate Fix: Restart with Delay

```bash
# Stop service
sudo systemctl stop pearlalgo-continuous-service.service

# Wait 60 seconds for rate limit reset
sleep 60

# Restart
sudo systemctl start pearlalgo-continuous-service.service
```

### Reduce API Load

Edit `config/config.yaml`:
```yaml
monitoring:
  workers:
    options:
      interval: 1800  # Increase to 30 minutes (was 15)
    options_intraday:
      interval: 120   # Increase to 2 minutes (was 60)
      enabled: false  # Or disable temporarily
```

### Test API Connection

```bash
python3 << 'EOF'
import asyncio
import os
from pearlalgo.data_providers.

async def test():
    api_key = os.getenv('MASSIVE_API_KEY')
    if not api_key:
        print("❌ MASSIVE_API_KEY not set")
        return
    
    provider = 
    
    # Test QQQ
    print("Testing QQQ...")
    data = await provider.get_latest_bar('QQQ')
    if data and data.get('close', 0) > 0:
        print(f"✅ QQQ: ${data['close']:.2f}")
    else:
        print("❌ QQQ: No valid data")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    # Test SPY
    print("Testing SPY...")
    data = await provider.get_latest_bar('SPY')
    if data and data.get('close', 0) > 0:
        print(f"✅ SPY: ${data['close']:.2f}")
    else:
        print("❌ SPY: No valid data")
    
    await provider.close()

asyncio.run(test())
EOF
```

## What Was Fixed

1. **Improved rate limiting:**
   - Increased minimum delay to 0.3 seconds between requests
   - Better handling of 429 errors with exponential backoff
   - Added delay between worker starts (2 seconds)

2. **Better data fetching:**
   - Uses `list_aggs` with yesterday-to-today range (more reliable)
   - Validates price > 0 before returning
   - Multiple retry attempts with backoff
   - Better error messages

3. **Worker startup:**
   - 2-second delay between worker registrations
   - Prevents simultaneous API bursts

## Monitoring

Check system health:
```bash
curl http://localhost:8080/healthz | jq '.components.data_provider'
```

Look for:
- `success_rate`: Should be > 0.8
- `circuit_breaker.open`: Should be false
- `data_freshness`: Should show recent updates

## If Problems Persist

1. **Check 
   - Visit 
   - Check if there are known issues
   - Verify your API key hasn't expired

2. **Review logs:**
   ```bash
   tail -100 logs/options_service.log | grep -i "error\|429\|rate limit"
   ```

3. **Temporarily reduce load:**
   - Disable one worker
   - Increase scan intervals
   - Reduce number of symbols

The system should now handle rate limits better and validate data before using it.
