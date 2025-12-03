# IBKR Deprecation Notice

## Status: Optional / Deprecated

**As of PearlAlgo v2, IBKR is now OPTIONAL and DEPRECATED.**

The system operates completely independently of IBKR using:
- Polygon.io / Tradier for market data
- Internal paper trading engines for simulation
- Vendor-agnostic broker abstraction

---

## Migration Path

### ✅ Recommended: Use New System

1. **Use Paper Broker** instead of IBKR:
   ```python
   broker = get_broker("paper", portfolio=portfolio)
   ```

2. **Use Polygon.io** for data:
   ```python
   provider = create_data_provider("polygon", api_key="your_key")
   ```

3. **No IBKR Gateway Required** - Start trading immediately

### ⚠️ Legacy: IBKR Still Available

IBKR broker/provider remains available for backward compatibility but:
- Not required for core functionality
- Will not receive new features
- May be removed in future versions

---

## What Changed

### Before (v1 - IBKR Required)
- Required IBKR Gateway running
- Mandatory IBKR connection checks
- System failed if IBKR unavailable

### After (v2 - IBKR Optional)
- ✅ System works without IBKR
- ✅ Optional IBKR support (deprecated)
- ✅ Multiple data providers available
- ✅ Professional paper trading engines

---

## Files Status

### Deprecated (Optional)
- `src/pearlalgo/brokers/ibkr_broker.py` - Optional, deprecated
- `src/pearlalgo/data_providers/ibkr_data_provider.py` - Optional, deprecated
- `scripts/debug_ibkr.py` - Optional utility

### New (Recommended)
- `src/pearlalgo/brokers/paper_broker.py` - ✅ Recommended
- `src/pearlalgo/data_providers/polygon_provider.py` - ✅ Recommended
- `src/pearlalgo/data_providers/tradier_provider.py` - ✅ Recommended

---

## Configuration

### Old (IBKR Required)
```yaml
broker:
  primary: "ibkr"  # Required
```

### New (IBKR Optional)
```yaml
broker:
  primary: "paper"  # Recommended
  # ibkr: Optional, deprecated
```

---

## Migration Guide

See `MIGRATION_GUIDE_IBKR_TO_V2.md` for complete migration instructions.

---

## Timeline

- **v2.0** (Current): IBKR optional, deprecated
- **v2.1** (Future): IBKR support may be removed
- **v3.0** (Future): IBKR code archived

---

## Support

For questions about migrating from IBKR:
1. See `MIGRATION_GUIDE_IBKR_TO_V2.md`
2. Review `ARCHITECTURE_V2.md` for new architecture
3. Check `IMPLEMENTATION_COMPLETE.md` for system status

**The new system is production-ready and recommended for all new deployments!**


