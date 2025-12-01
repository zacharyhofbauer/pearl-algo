# Account Analysis: DUK947427

## Account Overview
- **Account**: DUK947427
- **Account Type**: Individual
- **Base Currency**: USD
- **Report Period**: November 3-28, 2025

## Key Metrics (as of 11/28/2025)

### Net Asset Value
- **Ending NAV**: $241,887.78
- **Beginning NAV**: $1,007,386.68
- **Change in NAV**: -$765,498.90 (-4.05%)
- **Cumulative Return**: -4.05% (MTD/QTD/YTD)

### Open Positions (as of 11/28/2025)
| Symbol | Description | Quantity | Close Price | Value | Cost Basis | Unrealized P&L |
|--------|-------------|----------|-------------|-------|------------|----------------|
| ESZ5 | ES 19DEC25 | -1 (SHORT) | 6,859.50 | -$342,975.00 | -$339,510.25 | -$3,464.75 |
| NQZ5 | NQ 19DEC25 | -1 (SHORT) | 25,482.00 | -$509,640.00 | -$502,802.75 | -$6,837.25 |
| **Total Short** | | | | **-$852,615.00** | **-$842,313.00** | **-$10,302.00** |
| **Cash** | USD | | | **$241,887.78** | | |

### Performance Summary
- **Total Unrealized P&L**: -$10,302.00
- **Gross Exposure**: $852,615.00
- **Net Exposure**: -$852,615.00 (139.61% of NAV)
- **Cash**: $241,887.78 (100% of NAV)

### Trade Activity
- **ESZ5**: Sold 1 contract @ $6,790.25 (proceeds: $339,512.50)
- **NQZ5**: Sold 1 contract @ $25,140.25 (proceeds: $502,805.00)
- **Total Proceeds**: $842,317.50

### Deposits & Withdrawals
- **Net**: -$755,284.68
- Multiple adjustments on 11/26/2025

## Observations

1. **Account Matches Testing**: This is the same account (DUK947427) we've been testing with
2. **Positions Status**: Report shows ES and NQ short positions as of 11/28/2025
3. **During Testing**: We successfully closed these positions during manual testing on 12/1/2025
4. **Unrealized Loss**: Both positions were showing unrealized losses at report date
5. **High Leverage**: 139.61% net exposure indicates significant leverage

## Integration Notes

The automated trading system is connected to this account and:
- ✅ Successfully connects to IB Gateway
- ✅ Can place orders (verified 4 filled orders)
- ✅ Can view positions
- ✅ Can close positions
- ✅ Live trading is enabled

## Recommendations

1. **Position Monitoring**: The system can now monitor these positions in real-time
2. **Risk Management**: With 139.61% exposure, ensure risk limits are properly configured
3. **Automated Trading**: The system is ready to automate trading on this account
4. **Performance Tracking**: Can integrate with PortfolioAnalyst data for performance attribution

