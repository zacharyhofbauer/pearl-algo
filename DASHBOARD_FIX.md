# Dashboard Timezone Fix

**Date**: After testing  
**Issue**: TypeError when comparing tz-naive and tz-aware datetime objects

---

## Problem

The dashboard was crashing with:
```
TypeError: Cannot subtract tz-naive and tz-aware datetime-like objects.
```

This occurred in `compute_trade_statistics()` when calculating trade durations by subtracting `exit_time - entry_time` where one column was timezone-aware and the other was timezone-naive.

---

## Solution

Updated `scripts/dashboard.py` to normalize timezone handling:

1. **Detect timezone state** of both `entry_time` and `exit_time` columns
2. **Normalize timezones**:
   - If one is naive and one is aware, make both aware (assume UTC for naive)
   - If both are aware but different timezones, convert to same timezone
   - If both are naive, keep them naive
3. **Safe subtraction** after normalization
4. **Error handling** - gracefully skip duration calculation if timezone handling fails

---

## Code Changes

**File**: `scripts/dashboard.py`  
**Function**: `compute_trade_statistics()`  
**Lines**: ~260-290

Added timezone normalization logic before datetime subtraction to ensure both columns are in compatible timezone states.

---

## Testing

✅ Dashboard now runs successfully:
```bash
python scripts/dashboard.py --once
```

✅ All debug scripts working:
- `python scripts/debug_env.py` ✅
- `python scripts/debug_ibkr.py` ✅
- `python scripts/dashboard.py` ✅

---

**Dashboard is now fully functional and ready for use!**

