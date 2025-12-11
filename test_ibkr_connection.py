#!/usr/bin/env python3
"""Test IBKR Gateway connection"""
import asyncio
from ib_insync import IB
from pearlalgo.config.settings import get_settings

async def main():
    settings = get_settings()
    print(f"Testing connection to IB Gateway:")
    print(f"  Host: {settings.ib_host}")
    print(f"  Port: {settings.ib_port}")
    print(f"  Client ID: {settings.ib_data_client_id or settings.ib_client_id}")
    print()
    
    ib = IB()
    try:
        print("Attempting to connect...")
        await ib.connectAsync(
            settings.ib_host,
            settings.ib_port,
            clientId=settings.ib_data_client_id or settings.ib_client_id,
            timeout=10
        )
        print("✅ SUCCESS! Connected to IB Gateway")
        print(f"   Connection status: {ib.isConnected()}")
        
        # Try a simple request
        from ib_insync import Stock
        contract = Stock('SPY', 'SMART', 'USD')
        contracts = await ib.reqContractDetailsAsync(contract)
        if contracts:
            print(f"✅ Data access working! Found contract for SPY")
        
        ib.disconnect()
        print("\n✅ All tests passed! You can now run the continuous service.")
        return True
        
    except ConnectionRefusedError:
        print("❌ Connection refused!")
        print("\nTroubleshooting:")
        print("1. Start IB Gateway: ./scripts/start_ibgateway.sh")
        print("2. Enable API: Configure → Settings → API → Settings")
        print("3. Set Socket port to 4002 (paper) or 7497 (live)")
        print("4. Enable 'Enable ActiveX and Socket Clients'")
        print("5. Check if port is listening: ss -tuln | grep 4002")
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nCheck:")
        print("- IB Gateway is running")
        print("- API is enabled in settings")
        print("- Port matches your configuration")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
