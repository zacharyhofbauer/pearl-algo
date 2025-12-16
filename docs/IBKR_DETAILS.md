# IBKR Market Data Subscription Guide for Live MNQ Prices

## Current Status

Your system is **correctly configured** to request live market data. The Error 354 you're seeing means your IBKR account doesn't have the required market data subscription for CME futures (MNQ/NQ) **via API**.

**Important Distinction:**
- ✅ You have **"CME Event Contracts"** subscription (but this is for event contracts, not regular futures)
- ✅ You have **"US Real-Time Non Consolidated Streaming Quotes (IBKR-PRO)"** subscription
- ⚠️ **However**, these subscriptions are labeled **"Trader Workstation"** which typically means they're for GUI use in TWS, **not for API access**
- ❌ You need a **separate API-enabled subscription** for programmatic access

**Error Message:**
```
Error 354: Requested market data is not subscribed. 
Check API status by selecting the Account menu then under Management 
choose Market Data Subscription Manager
```

**Your Current Subscriptions (from screenshot):**
- Market Data API access: ✅ **Enabled** (signed 2025-11-26)
- Subscriber status: **Non-Professional**
- Active subscriptions: CME Event Contracts, US Real-Time Quotes (IBKR-PRO) - but these are **TWS-only**
- **Missing:** CME Real-Time (Level 1) for **API access**

## Required Subscription Options

To get **live, real-time prices** for MNQ futures, you need to subscribe to one of these packages:

### Option 1: CME Real-Time (NP,L1) - **RECOMMENDED** ⭐
- **Cost:** $1.55/month (increases from $1.25 on January 1, 2026)
- **What you get:** Real-time top-of-book data for futures traded on CME
- **Explicitly includes:** ES, **NQ**, and HE contracts (perfect for your MNQ/NQ needs!)
- **Fee Waiver:** Monthly fee waived if you generate $20+ in commissions
- **Best for:** Most users - cheapest option that provides live NQ prices
- **Link:** [IBKR Market Data Pricing](https://www.interactivebrokers.co.uk/en/pricing/market-data-pricing.php)

### Option 2: US Futures Value Bundle PLUS
- **Cost:** $5.00/month
- **What you get:** Real-time Level 2 (depth-of-book) data for CBOT, CME, COMEX, NYMEX futures
- **Best for:** If you want order book depth (bid/ask levels)
- **Link:** [IBKR Market Data Pricing](https://brokerage.ibkr.com/en/pricing/research-news-marketdata.php)

### Option 3: US Securities Snapshot and Futures Value Bundle
- **Cost:** $10.00/month (waived if you generate $30+ in commissions)
- **What you get:** Real-time top-of-book for CME futures + US stocks + bonds
- **Best for:** If you trade multiple asset classes and generate commissions

## How to Subscribe

### Step 1: Log into IBKR Client Portal
1. Go to [Client Portal](https://www.interactivebrokers.com/portal/)
2. Log in with your IBKR account credentials

### Step 2: Navigate to Market Data Subscriptions
1. Click on **"Account Management"** (top menu)
2. Select **"Manage Market Data Subscriptions"** (under Account Management)
   - Alternative path: **Account → Settings → Market Data Subscriptions**

### Step 3: Subscribe to CME Real-Time (NP,L1)
1. In the Market Data Subscriptions page, find **"CME Real-Time (NP,L1)"**
   - **Description:** "Provides top of book data for futures traded on CME"
   - **Examples:** ES, **NQ**, and HE contracts (this is exactly what you need!)
2. Review the details:
   - **Cost:** USD 1.55/month (increases from $1.25 on Jan 1, 2026)
   - **Fee Waiver:** Waived if you generate $20+ in monthly commissions
3. Click **"Subscribe"** or **"Add"**
4. Review the terms and confirm subscription
5. The subscription will be active immediately (or within a few minutes)

**Note:** This subscription works for both TWS (Trader Workstation) and API access. The "NP,L1" designation means "Non-Professional, Level 1" which is perfect for your use case.

### Step 4: Verify Subscription
1. After subscribing, wait 1-2 minutes for activation
2. Restart your NQ Agent service:
   ```bash
   ./scripts/lifecycle/stop_nq_agent_service.sh
   ./scripts/lifecycle/start_nq_agent_service.sh
   ```
3. Check logs - you should see:
   - ✅ No more "Error 354" messages
   - ✅ Real-time price updates (not stale 11+ minute old data)
   - ✅ Data freshness warnings should disappear

## What Changes After Subscription

### Before (Current State):
```
Error 354: Requested market data is not subscribed
⚠️ Historical fallback data for MNQ is stale: 11.1 minutes old
Using historical data fallback for MNQ (real-time subscription not available)
```

### After (With Subscription):
```
✅ Real-time market data subscription active
✅ Live price updates every few seconds
✅ No stale data warnings
✅ Current market price (not 11+ minutes old)
```

## Code Status

**Good news:** Your code is already set up correctly! No code changes needed.

The system:
- ✅ Already requests real-time data via `reqMktData()` API call
- ✅ Falls back to historical data when subscription not available (current behavior)
- ✅ Will automatically use live data once subscription is active

**Location in code:**
- `src/pearlalgo/data_providers/ibkr_executor.py` (lines 87-138)
- Handles Error 354 gracefully and falls back to historical data

## Cost Summary

| Subscription | Monthly Cost | What You Get | Fee Waiver |
|-------------|--------------|--------------|------------|
| **CME Real-Time (NP,L1)** | **$1.55** | Real-time NQ/MNQ prices (recommended) | Waived if $20+ commissions |
| US Futures Value Bundle PLUS | $5.00 | Level 2 depth data for all US futures | Varies |
| US Securities + Futures Bundle | $10.00 | Futures + stocks + bonds | Waived if $30+ commissions |

**Note:** CME Real-Time (NP,L1) price increases from $1.25 to $1.55 on January 1, 2026.

## FAQ

### Q: I already have CME subscriptions - why isn't it working?
**A:** You likely have **TWS-only subscriptions** (for Trader Workstation GUI). API access requires a separate subscription or the subscription needs to explicitly support API access. Check if your subscription mentions "API" or "Market Data API" in the name.

### Q: Do I need to change any API settings?
**A:** No. Your API settings are correct. The subscription is account-level, not API-level. However, make sure your Market Data API Acknowledgement is signed (which it is - signed 2025-11-26).

### Q: Will my existing "US Real-Time Non Consolidated Streaming Quotes (IBKR-PRO)" work?
**A:** Possibly, but it's labeled "Trader Workstation" which suggests it's for GUI use. You may need to subscribe to a specific API-enabled package. Try subscribing to "CME Real-Time (Level 1)" and see if it works.

### Q: Will the code work automatically after subscribing?
**A:** Yes. Once you subscribe and wait 1-2 minutes, restart the service and it will automatically use live data.

### Q: Can I use delayed data for free?
**A:** IBKR provides some delayed data (15-20 minute delay), but for live trading signals, you need real-time subscription.

### Q: What if I only want to test?
**A:** You can test with the current historical data fallback, but prices will be 11+ minutes old. For production trading, you need the $1.25/month subscription.

### Q: How do I cancel if needed?
**A:** Go to Account Management → Market Data Subscriptions → Find your subscription → Click "Unsubscribe"

## Verification Steps

After subscribing, verify it's working:

1. **Check logs for Error 354:**
   ```bash
   tail -f logs/nq_agent.log | grep -i "error 354"
   ```
   Should see: No Error 354 messages

2. **Check for real-time data:**
   ```bash
   tail -f logs/nq_agent.log | grep -i "real-time\|stale"
   ```
   Should see: Real-time data messages, no stale warnings

3. **Check Telegram notifications:**
   - Price timestamps should be current (within seconds, not 11+ minutes)
   - No "stale data" warnings in status messages

## Next Steps

1. ✅ **Subscribe to CME Real-Time (NP,L1)** - $1.55/month
   - This subscription **explicitly includes NQ contracts** (as shown in the description)
   - Works for both TWS and API access
   - Fee waived if you generate $20+ in monthly commissions
2. ✅ Wait 1-2 minutes for activation
3. ✅ Restart IBKR Gateway (to refresh entitlements):
   ```bash
   pkill -f "java.*IBC.jar"
   sleep 5
   ./scripts/gateway/start_ibgateway_ibc.sh
   ```
4. ✅ Restart NQ Agent service:
   ```bash
   ./scripts/lifecycle/start_nq_agent_service.sh
   ```
5. ✅ Verify no Error 354 in logs
6. ✅ Confirm live prices in Telegram notifications (should be current, not 11+ minutes old)

## Troubleshooting: If Subscription Still Doesn't Work

If you subscribe but still get Error 354:

1. **Check subscription type:** Make sure it's not just "Trader Workstation" - you need API-enabled
2. **Wait longer:** Some subscriptions take 5-10 minutes to activate
3. **Restart Gateway:** After subscribing, restart IBKR Gateway:
   ```bash
   pkill -f "java.*IBC.jar"
   sleep 5
   ./scripts/gateway/start_ibgateway_ibc.sh
   ```
4. **Contact IBKR Support:** If still not working, contact IBKR to confirm your subscription includes API access for CME futures

---

**Last Updated:** 2025-12-16  
**Subscription Required:** CME Real-Time (NP,L1) - $1.55/month (waived if $20+ commissions)  
**Status:** Code ready - just needs subscription activation  
**Confirmation:** Subscription explicitly includes NQ contracts (ES, NQ, HE)
