# Migration Guide: Polygon.io to Massive.com

## Overview

Polygon.io has rebranded to **Massive.com** (October 2025). This guide helps you migrate your PearlAlgo system from Polygon to Massive.

## What Changed

- **API Base URL**: `https://api.polygon.io` → `https://api.massive.com`
- **Environment Variable**: `POLYGON_API_KEY` → `MASSIVE_API_KEY`
- **Python Package**: `polygon-api-client` → `massive`
- **Config Keys**: `polygon` → `massive`

## Migration Steps

### 1. Update Environment Variables

**Before:**
```bash
POLYGON_API_KEY=your_key_here
```

**After:**
```bash
MASSIVE_API_KEY=your_key_here
```

**Note:** Your existing Polygon API key will work with Massive - no need to generate a new one.

### 2. Update Configuration File

Edit `config/config.yaml`:

**Before:**
```yaml
data:
  fallback:
    polygon:
      api_key: "${POLYGON_API_KEY}"

monitoring:
  data_feeds:
    polygon:
      rate_limit: 5
```

**After:**
```yaml
data:
  fallback:
    massive:
      api_key: "${MASSIVE_API_KEY}"

monitoring:
  data_feeds:
    massive:
      rate_limit: 5
```

### 3. Update Dependencies

The system now uses the `massive` Python package instead of `polygon-api-client`.

**Install:**
```bash
pip install massive
```

**Remove old package (optional):**
```bash
pip uninstall polygon-api-client
```

### 4. Update Code References

All code has been updated to use `MassiveDataProvider` instead of `PolygonDataProvider`. If you have custom code:

**Before:**
```python
from pearlalgo.data_providers.polygon_provider import PolygonDataProvider
provider = PolygonDataProvider(api_key=os.getenv("POLYGON_API_KEY"))
```

**After:**
```python
from pearlalgo.data_providers.massive_provider import MassiveDataProvider
provider = MassiveDataProvider(api_key=os.getenv("MASSIVE_API_KEY"))
```

### 5. New Features

The migration includes several improvements:

1. **Contract Discovery**: Automatically resolves base symbols (ES, NQ) to active contracts (ESU5, NQU5)
2. **Options Scanning**: New options module for equity options swing trading
3. **Enhanced Rate Limiting**: Token bucket algorithm for better rate limit management
4. **Improved Reconnection**: Exponential backoff with jitter for more reliable connections

## Backward Compatibility

The system maintains limited backward compatibility:

- `"polygon"` provider name in factory still works (maps to Massive)
- Old config keys may work temporarily, but should be updated

## Verification

After migration, verify everything works:

```bash
# Test API key
python3 -c "
from pearlalgo.data_providers.massive_provider import MassiveDataProvider
import os
provider = MassiveDataProvider(api_key=os.getenv('MASSIVE_API_KEY'))
print('✅ Massive provider initialized successfully')
"

# Test contract discovery
python3 -c "
from pearlalgo.futures.contract_discovery import ContractDiscovery
import os
import asyncio
discovery = ContractDiscovery(api_key=os.getenv('MASSIVE_API_KEY'))
contract = asyncio.run(discovery.get_active_contract('ES'))
print(f'✅ Active ES contract: {contract}')
"
```

## Troubleshooting

### API Key Issues

If you see "MASSIVE_API_KEY is required":
1. Check your `.env` file has `MASSIVE_API_KEY=...`
2. Verify the key is valid at https://massive.com/dashboard
3. Restart the service after updating environment variables

### Contract Discovery Fails

If contract discovery fails:
1. Check API key has futures data access
2. Verify network connectivity
3. Check logs for specific error messages

### Rate Limit Errors

If you see rate limit errors:
1. The system now uses token bucket rate limiting
2. Adjust `rate_limit` in config if needed
3. Check your Massive subscription tier limits

## Support

For issues with the migration:
1. Check logs: `logs/continuous_service.log`
2. Review health endpoint: `curl http://localhost:8080/healthz`
3. Verify API key at https://massive.com/dashboard

## Additional Resources

- Massive API Documentation: https://massive.com/docs
- Python Client: https://github.com/massive-com/client-python
- PearlAlgo Documentation: See `HOW_TO_USE_24_7_SYSTEM.md`
