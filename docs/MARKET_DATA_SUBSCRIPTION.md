# IBKR Market Data Subscription Guide for Live MNQ Prices

## ⚠️ CRITICAL: Payment Status & API Acknowledgement Required

**Even if you have "CME Real-Time (NP,L2)" subscribed, two things are required:**

1. **Payment/Account Balance:** Subscription must be paid (or waived) AND account must have minimum USD 500 balance
2. **Market Data API Acknowledgement:** Must be completed separately to enable API access

Many users have active subscriptions but still get Error 354 due to payment issues or missing API acknowledgement.

### Step 1: Complete Market Data API Acknowledgement (REQUIRED)

1. **Log into IBKR Client Portal**: https://www.interactivebrokers.com/portal/
2. **Navigate to Settings**:
   - Click on **"Welcome [Your Name]"** in the top right corner
   - Select **"Settings"**
3. **Find Market Data API Acknowledgement**:
   - Click on **"Market Data Subscriptions"**
   - On the right side, look for **"Market Data API Acknowledgement"**
   - Click the **blue cogwheel icon** (⚙️) to modify settings
4. **Enable and Sign**:
   - Enable the functionality
   - Review the terms
   - **Digitally sign the form**
5. **Restart Everything**:
   - Log out of Client Portal
   - Log back in
   - **Restart IB Gateway**: `./scripts/gateway/stop_ibgateway_ibc.sh && ./scripts/gateway/start_ibgateway_ibc.sh`
   - Restart your NQ Agent service

**This acknowledgement is MANDATORY for API access, even if your subscription is active.**

### Step 2: API User Activity Certification (For Futures Trading)

If you're trading futures via API, you also need to complete:
- **API User Activity Certification** (required by CME Rule 576)
- This is typically prompted upon login
- If not prompted, contact IBKR support

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

### Step 4: Complete Market Data API Acknowledgement (CRITICAL!)

**This is the most common reason for Error 354 even with active subscriptions!**

1. **Log into IBKR Client Portal**: https://www.interactivebrokers.com/portal/
2. **Go to Settings → Market Data Subscriptions**
3. **Find "Market Data API Acknowledgement"** (right side of page)
4. **Click the blue cogwheel icon (⚙️)** to modify
5. **Enable and digitally sign** the acknowledgement form
6. **Log out and log back in** to Client Portal
7. **Restart IB Gateway**:
   ```bash
   ./scripts/gateway/stop_ibgateway_ibc.sh
   ./scripts/gateway/start_ibgateway_ibc.sh
   ```

**Without this acknowledgement, your subscription won't work via API, even if it's active for TWS!**

### Step 5: Verify Subscription
1. After subscribing AND completing API acknowledgement, wait 1-2 minutes for activation
2. Restart your NQ Agent service:
   ```bash
   ./scripts/lifecycle/stop_nq_agent_service.sh
   ./scripts/lifecycle/start_nq_agent_service.sh
   ```
3. Check logs - you should see:
   - ✅ No more "Error 354" messages
   - ✅ Real-time price updates (not stale 11+ minute old data)
   - ✅ Data freshness warnings should disappear
   - ✅ Level 2 order book data if you have L2 subscription

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

## Troubleshooting Error 354 with Active Subscription

### Problem: "I have CME Real-Time (NP,L2) subscribed but still get Error 354"

**Possible Causes (in order of likelihood):**

#### 1. Payment/Account Balance Issue ⚠️ **MOST LIKELY IF SUBSCRIPTION SHOWS AS ACTIVE**

IBKR requires:
- **Minimum account balance:** USD 500 (or equivalent) to maintain market data subscriptions
- **Payment status:** Subscription must be paid (or waived via commissions)
- **Account equity:** Must meet minimum requirements

**Check:**
- Client Portal → Account → Account Summary
- Verify account balance is above USD 500
- Check if subscription fee is being charged or waived
- Look for any payment warnings or subscription suspension notices

**If unpaid/insufficient balance:**
- Add funds to meet minimum balance requirement
- Wait 1-2 minutes for system to update
- Restart Gateway and service

#### 2. Market Data API Acknowledgement Not Completed

Even with active subscription, you MUST complete the Market Data API Acknowledgement.

**Steps:**
1. Client Portal → Settings → Market Data Subscriptions
2. Find "Market Data API Acknowledgement" (right side)
3. Click blue cogwheel (⚙️) → Enable → Sign
4. Log out/in → Restart Gateway → Restart Service

#### 3. Gateway Needs Restart After Subscription Activation

**Solution:**
```bash
./scripts/gateway/stop_ibgateway_ibc.sh
./scripts/gateway/start_ibgateway_ibc.sh
```

#### 4. Subscription Activation Delay

IBKR subscriptions can take 1-24 hours to fully activate for API access.

**Solution:** Wait and try again, or contact IBKR support.

### Problem: "Error 310: Can't find the subscribed market depth"

**Solution:** This usually means:
1. Payment/balance issue (see above) - **most common**
2. Market Data API Acknowledgement not completed
3. Gateway needs restart after acknowledgement
4. Subscription not yet activated (wait 1-2 minutes)

### Problem: "Subscription works in TWS but not via API"

**Solution:** This could mean:
1. Payment/balance issue preventing API access (even if TWS works)
2. Market Data API Acknowledgement not completed
3. Subscription needs to be explicitly enabled for API (check settings)

## FAQ

### Q: I already have CME Real-Time (NP,L2) subscribed - why am I still getting Error 354?
**A:** **This is the #1 issue!** Even with an active subscription, you MUST complete the **Market Data API Acknowledgement** separately. This is a compliance requirement that enables API access to your subscriptions.

**Solution:**
1. Client Portal → Settings → Market Data Subscriptions
2. Find "Market Data API Acknowledgement" (right side)
3. Click blue cogwheel (⚙️) → Enable → Digitally sign
4. Log out/in → Restart Gateway → Restart Service

**Without this acknowledgement, subscriptions won't work via API, even if they work in TWS!**

### Q: Do I need to change any API settings?
**A:** No. Your API settings are correct. However, you MUST complete the Market Data API Acknowledgement (see above). The subscription is account-level, but API access requires this separate acknowledgement.

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




