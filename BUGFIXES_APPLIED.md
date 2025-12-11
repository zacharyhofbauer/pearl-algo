# Bug Fixes Applied

## Issues Found and Fixed

### 1. TypeError: unsupported format string passed to NoneType.__format__

**Location:** `src/pearlalgo/futures/exit_signals.py:514`

**Problem:**
```python
f"Stop: ${signal.stop_loss:.2f if signal.stop_loss else 'N/A'}, "
```
The f-string was trying to format `None` with `.2f` before the conditional check evaluated.

**Fix:**
```python
stop_str = f"${signal.stop_loss:.2f}" if signal.stop_loss else "N/A"
target_str = f"${signal.take_profit:.2f}" if signal.take_profit else "N/A"
logger.warning(
    f"Market data missing for {symbol} in state. "
    f"Signal: {signal.direction} @ ${signal.entry_price:.2f}, "
    f"Stop: {stop_str}, "
    f"Target: {target_str}"
)
```

### 2. get_latest_bar() Argument Error

**Location:** `src/pearlalgo/futures/exit_signals.py:318, 348`

**Problem:**
```python
provider.get_latest_bar(symbol, "15m")  # Wrong - takes only symbol
```

**Fix:**
```python
provider.get_latest_bar(symbol)  # Correct - only symbol parameter
```

Also improved handling of different return types (dict, object, Series).

## Testing

Run the quick test to verify:
```bash
source .venv/bin/activate
python3 quick_test.py
```

## Next Steps

1. **Restart the service:**
   ```bash
   python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml
   ```

2. **Monitor for errors:**
   ```bash
   tail -f logs/continuous_service.log | grep -i error
   ```

3. **Check health:**
   ```bash
   curl http://localhost:8080/healthz | jq
   ```

The service should now run without the TypeError and argument errors.
