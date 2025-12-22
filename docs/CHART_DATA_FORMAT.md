# Chart Generator Data Format Comparison

## Data Format Flow

### Test Script (`test_mplfinance_chart.py`)

**Input Data Format:**
```python
DataFrame with columns:
- 'timestamp' (datetime)
- 'open' (float)
- 'high' (float)
- 'low' (float)
- 'close' (float)
- 'volume' (int)
```

**Example:**
```python
data = pd.DataFrame({
    'timestamp': pd.date_range(...),
    'open': [25000.0, ...],
    'high': [25001.0, ...],
    'low': [24999.0, ...],
    'close': [25000.5, ...],
    'volume': [1000, ...]
})
```

### Production Code (Telegram Handler)

**Input Data Format:**
```python
buffer_data: pd.DataFrame with columns:
- 'timestamp' (datetime) OR timestamp in index
- 'open' (float)
- 'high' (float)
- 'low' (float)
- 'close' (float)
- 'volume' (int)
```

**Same format as test script!** Both use lowercase column names.

## Data Transformation in Chart Generator

### Step 1: `_prepare_data()` 
Converts input data to mplfinance format:

**Input:** Lowercase columns (`open`, `high`, `low`, `close`, `volume`, `timestamp`)
**Output:** Uppercase columns (`Open`, `High`, `Low`, `Close`, `Volume`) with timestamp as index

```python
# Before transformation
df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']

# After transformation
df.index = DatetimeIndex (from timestamp)
df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
```

### Step 2: `_add_indicators()`
Uses the transformed data (uppercase) for mplfinance, but converts back to lowercase for VWAPCalculator:

**For Moving Averages:**
- Uses uppercase: `data['Close'].rolling(period).mean()`

**For VWAP:**
- Converts back to lowercase before calling VWAPCalculator
- VWAPCalculator expects: `open`, `high`, `low`, `close`, `volume`

## Key Differences

| Aspect | Test Script | Production Code |
|--------|-------------|-----------------|
| **Input Format** | Lowercase columns | Lowercase columns ✅ Same |
| **Data Source** | Generated sample data | Real buffer_data from agent |
| **Data Size** | 100 bars | `buffer_data.tail(100)` (last 100 bars) |
| **Timestamp** | Column | Column or Index |
| **VWAP Calculation** | Uses lowercase data | Converts uppercase→lowercase for VWAP |

## VWAP Error Fix

**Problem:** VWAPCalculator was receiving uppercase column names (`High`, `Low`, etc.) but expects lowercase (`high`, `low`, etc.)

**Solution:** Convert data back to lowercase before passing to VWAPCalculator:

```python
# Convert back to lowercase for VWAPCalculator
vwap_df = data.reset_index().copy()
vwap_df = vwap_df.rename(columns={
    'Open': 'open',
    'High': 'high',
    'Low': 'low',
    'Close': 'close',
})
if 'Volume' in vwap_df.columns:
    vwap_df = vwap_df.rename(columns={'Volume': 'volume'})
vwap_data = vwap_calc.calculate_vwap(vwap_df)
```

## Data Flow Summary

```
Input (buffer_data)
  ↓
[Lowercase: open, high, low, close, volume, timestamp]
  ↓
_prepare_data()
  ↓
[Uppercase: Open, High, Low, Close, Volume, timestamp→index]
  ↓
_add_indicators()
  ├─→ Moving Averages: Uses uppercase (data['Close'])
  └─→ VWAP: Converts back to lowercase for VWAPCalculator
  ↓
mplfinance.plot() uses uppercase format
```

## Conclusion

Both test script and production code use the **same input data format** (lowercase columns). The chart generator handles the transformation internally to work with mplfinance (which requires uppercase) and VWAPCalculator (which requires lowercase).

## Verification Results

**Test Results:**
- ✅ Test script format: `['timestamp', 'open', 'high', 'low', 'close', 'volume']` (lowercase)
- ✅ Production buffer format: `['timestamp', 'open', 'high', 'low', 'close', 'volume']` (lowercase)
- ✅ **Both formats are IDENTICAL**

**After Transformation:**
- After `_prepare_data()`: `['Open', 'High', 'Low', 'Close', 'Volume']` with timestamp as index
- After `reset_index()` for VWAP: `['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']` (uppercase)
- **Fix Applied:** Convert back to lowercase before VWAPCalculator: `['timestamp', 'open', 'high', 'low', 'close', 'volume']` ✅

**The VWAP error was caused by:**
- Data transformed to uppercase for mplfinance
- VWAPCalculator called with uppercase columns
- VWAPCalculator expects lowercase → **FIXED** by converting back to lowercase

