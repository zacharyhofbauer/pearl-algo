# Manual Trading Test Guide

## Quick Start

Test entering and closing trades manually to verify the system works.

### Step 1: Test Connection

```bash
cd ~/pearlalgo-dev-ai-agents
source .venv/bin/activate
python scripts/test_broker_connection.py
```

This will:
- ✅ Test IB Gateway connection
- ✅ Test contract lookup (MES, MNQ, MGC)
- ✅ Check current positions
- ✅ Verify broker is working

### Step 2: Manual Trading Test

```bash
python scripts/manual_trade_test.py
```

This opens an interactive menu where you can:
1. **Show Positions** - View current open positions
2. **Enter Trade** - Manually place a trade
3. **Close Position** - Close an open position
4. **Refresh Positions** - Update position data
5. **Exit** - Quit

## What to Test

### Test 1: Enter a Trade

1. Run `python scripts/manual_trade_test.py`
2. Select option `2` (Enter Trade)
3. Enter:
   - Symbol: `MES` (or any micro contract)
   - Side: `LONG` or `SHORT`
   - Size: `1` (start small!)
   - Price: Leave empty for market order
4. Confirm the order

**Expected:**
- Order submitted successfully
- Position appears in "Show Positions"

### Test 2: Check Position

1. Select option `1` (Show Positions)
2. Verify:
   - Symbol is correct
   - Size is correct
   - Entry price is recorded
   - P&L is updating

### Test 3: Close Position

1. Select option `3` (Close Position)
2. Select the position to close
3. Confirm close

**Expected:**
- Position closed
- P&L realized
- Position removed from list

## Troubleshooting

### Connection Fails?

```bash
# Check Gateway status
pearlalgo gateway status

# Restart Gateway if needed
pearlalgo gateway restart --wait
```

### Contract Not Found?

- Verify symbol is correct (MES, MNQ, MGC, MYM, MCL)
- Check if market is open
- Try a different symbol

### Order Fails?

- Check Gateway connection
- Verify account has permissions
- Check if market is open
- Try with paper trading account first

## Notes

- **Start Small**: Use 1 contract for testing
- **Paper Trading**: Make sure you're on paper account
- **Market Hours**: Some contracts have limited hours
- **Real Orders**: This will place REAL orders if connected to live account!

## Next Steps

Once manual trading works:
1. ✅ Connection verified
2. ✅ Order execution works
3. ✅ Position tracking works
4. ✅ P&L calculation works

Then automated trading should work too!

