# Futures Re-enablement Guide

This guide documents the steps to re-enable futures trading when Massive's futures API becomes available.

## Overview

The futures module has been disabled and moved to `src/pearlalgo/futures/__init__.py` while Massive's futures API is unavailable. The system currently focuses exclusively on equity options (QQQ, SPY) for intraday and swing trading.

## Re-enablement Checklist

### 1. Verify Massive Futures API Availability

- [ ] Confirm Massive API supports futures data (ES, NQ)
- [ ] Test API endpoints for futures contracts
- [ ] Verify contract resolution (ESU5, NQU5, etc.)
- [ ] Test historical futures data access

### 2. Re-enable Futures Module

**File:** `src/pearlalgo/futures/__init__.py`

- [ ] Review disabled futures code
- [ ] Update `get_active_futures_contract()` implementation
- [ ] Update `is_futures_symbol()` to return True for futures
- [ ] Test futures contract resolution

### 3. Update Signal Router

**File:** `src/pearlalgo/core/signal_router.py`

- [ ] Update `is_futures()` method to properly detect futures symbols
- [ ] Update `route_signal()` to route futures signals to futures handler
- [ ] Test signal routing for both options and futures

### 4. Update Risk Manager

**File:** `src/pearlalgo/agents/risk_manager_agent.py`

- [ ] Re-enable futures risk rules
- [ ] Add `futures_max_risk` configuration
- [ ] Update position sizing for futures
- [ ] Test risk calculations for futures positions

### 5. Update Continuous Service

**File:** `src/pearlalgo/monitoring/continuous_service.py`

- [ ] Re-enable futures worker (currently commented out at line 390)
- [ ] Update worker initialization
- [ ] Add futures symbols to configuration
- [ ] Test futures worker startup

### 6. Update Configuration

**File:** `config/config.yaml`

- [ ] Add futures worker configuration:
  ```yaml
  monitoring:
    workers:
      futures:
        enabled: true
        symbols: ["ES", "NQ"]
        interval: 60
        strategy: "intraday_swing"
  ```
- [ ] Add futures risk parameters
- [ ] Update data sources to include futures

### 7. Update Data Provider

**File:** `src/pearlalgo/data_providers/massive_provider.py`

- [ ] Re-enable futures contract resolution (currently removed)
- [ ] Test `get_latest_bar()` for futures symbols
- [ ] Test `fetch_historical()` for futures
- [ ] Verify contract roll handling

### 8. Testing

- [ ] Unit tests for futures contract resolution
- [ ] Integration tests for futures data ingestion
- [ ] Test futures signal generation
- [ ] Test futures position tracking
- [ ] Test futures exit signals

### 9. Documentation

- [ ] Update `HOW_TO_USE_24_7_SYSTEM.md` with futures instructions
- [ ] Update `README.md` to reflect futures support
- [ ] Create futures-specific documentation if needed

## Migration Notes

### Contract Resolution

Futures contracts need to be resolved from symbols (ES, NQ) to active contracts (ESU5, NQU5). The disabled module contains placeholder logic that needs to be implemented using Massive's futures API.

### Risk Management

Futures typically use different risk parameters than options:
- Futures: Higher risk per trade (2% default)
- Options: Lower risk per trade (1% default) due to leverage

### Data Structure

Futures data structure is similar to stocks but requires:
- Contract roll detection
- Expiration date handling
- Front month contract tracking

## Files Modified During Disablement

1. `src/pearlalgo/futures/__init__.py` - Created disabled module
2. `src/pearlalgo/core/signal_router.py` - Added `is_futures()` returning False
3. `src/pearlalgo/agents/risk_manager_agent.py` - Removed futures-specific risk logic
4. `src/pearlalgo/monitoring/continuous_service.py` - Removed futures worker
5. `config/config.yaml` - Removed futures worker configuration
6. `src/pearlalgo/data_providers/massive_provider.py` - Removed futures contract resolution

## Rollback Plan

If re-enablement causes issues:

1. Revert changes to `signal_router.py` (set `is_futures()` to return False)
2. Disable futures worker in `continuous_service.py`
3. Remove futures worker from `config.yaml`
4. System will continue operating in options-only mode

## Support

For questions or issues during re-enablement, refer to:
- Massive API documentation for futures endpoints
- Original futures implementation (if available in git history)
- Options implementation as reference for similar patterns
