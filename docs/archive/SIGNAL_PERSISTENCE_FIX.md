# Signal Persistence Fix

## Problem

Signals from last night were not visible when using `/signals` command, even though the agent reported "2 signals" in status messages.

## Root Cause

**Format Mismatch**: The `state_manager.save_signal()` method was saving signals in the wrong format:

- **What it was saving**: Just the signal dictionary directly: `{"signal_id": "...", "type": "...", "direction": "...", ...}`
- **What `/signals` command expected**: A wrapped format: `{"signal_id": "...", "timestamp": "...", "status": "generated", "signal": {...}}`

This meant:
1. Signals WERE being saved to `data/nq_agent_state/signals.jsonl`
2. But the `/signals` command couldn't parse them correctly
3. The file might also be empty if signals weren't being processed

## Fix Applied

### 1. Fixed `state_manager.save_signal()` Format
**File**: `src/pearlalgo/nq_agent/state_manager.py`

Now saves signals in the correct format:
```json
{
  "signal_id": "momentum_breakout_1234567890.123",
  "timestamp": "2025-12-19T20:30:45.123456+00:00",
  "status": "generated",
  "signal": {
    "signal_id": "momentum_breakout_1234567890.123",
    "type": "momentum_breakout",
    "direction": "long",
    "entry_price": 25500.0,
    ...
  }
}
```

### 2. Enhanced `/signals` Command
**File**: `src/pearlalgo/nq_agent/telegram_command_handler.py`

- Now handles both old and new formats (backward compatible)
- Shows total signal count
- Better error messages if file is empty or missing
- More informative when no signals found

## What This Means

### Going Forward
- **New signals** will be saved in the correct format
- **`/signals` command** will display them properly
- **Signal count** will persist across restarts

### Existing Signals
- If you have signals in the old format, the `/signals` command will automatically convert them
- If the file is empty, you'll need to wait for new signals to be generated

## Verification Steps

1. **Check if signals file exists and has content**:
   ```bash
   ls -lh data/nq_agent_state/signals.jsonl
   wc -l data/nq_agent_state/signals.jsonl  # Count lines
   ```

2. **View signals file content** (first few lines):
   ```bash
   head -3 data/nq_agent_state/signals.jsonl | python3 -m json.tool
   ```

3. **Test `/signals` command**:
   - Send `/signals` in Telegram
   - Should show total count and recent signals
   - If empty, will show helpful message

4. **Monitor for new signals**:
   - When agent generates new signals, they should now be saved correctly
   - Check logs: `grep -i "Saved signal" logs/nq_agent.log`

## Why Signals From Last Night Are Gone

The signals from last night were likely:
1. **Never saved** - If `state_manager.save_signal()` was failing silently
2. **Saved in wrong format** - And then couldn't be read back
3. **File was cleared** - During a restart or manual cleanup

**Going forward**, new signals will be saved correctly and persist across restarts.

## Related Issues Fixed

- Signal count now persists across restarts (see `ADDITIONAL_FIXES.md`)
- Signal format now matches what `/signals` command expects
- Better error handling and logging for signal persistence
