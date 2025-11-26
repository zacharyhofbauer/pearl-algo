#!/usr/bin/env python
"""Test IBKR contract definitions."""
from ib_insync import IB, Future, Stock, ContFuture
import sys

def main():
    ib = IB()
    try:
        # Connect
        ib.connect('127.0.0.1', 4002, clientId=999)
        print("Connected to IBKR\n")
        
        # First, explore what ES contracts are available using reqMatchingSymbols
        print("Exploring available ES contracts:")
        try:
            results = ib.reqMatchingSymbols('ES')
            for res in results:
                print(res)
        except Exception as e:
            print(f"✗ reqMatchingSymbols failed: {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test different contract formats for ES
        print("Testing ES contract formats:")
        
        # Try continuous future
        try:
            es_cont = ContFuture('ES', 'GLOBEX')
            details = ib.reqContractDetails(es_cont)
            if details:
                print(f"✓ ContFuture ES works: {details[0].contract.localSymbol}")
        except Exception as e:
            print(f"✗ ContFuture ES failed: {e}")
        
        # Try with specific expiry format
        test_formats = [
            Future('ES', '202412', 'GLOBEX'),  # YYYYMM format
            Future('ES', '20241220', 'GLOBEX'),  # YYYYMMDD format
            Future(localSymbol='ESZ4', exchange='GLOBEX'),  # Local symbol only
            Future(localSymbol='ES DEC 24', exchange='GLOBEX'),  # Verbose format
        ]
        
        for contract in test_formats:
            try:
                details = ib.reqContractDetails(contract)
                if details:
                    c = details[0].contract
                    print(f"✓ Works: {contract} -> localSymbol={c.localSymbol}, expiry={c.lastTradeDateOrContractMonth}")
            except Exception as e:
                print(f"✗ Failed: {contract} -> {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test NQ
        print("Testing NQ contract formats:")
        try:
            nq_results = ib.reqMatchingSymbols('NQ')
            print("Available NQ contracts:")
            for res in nq_results:
                print(res)
        except Exception as e:
            print(f"✗ reqMatchingSymbols NQ failed: {e}")

        try:
            nq_test = Future('NQ', '202412', 'GLOBEX')
            details = ib.reqContractDetails(nq_test)
            if details:
                c = details[0].contract
                print(f"✓ NQ works: localSymbol={c.localSymbol}, expiry={c.lastTradeDateOrContractMonth}")
        except Exception as e:
            print(f"✗ NQ failed: {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test stocks (should work fine)
        print("Testing stock contracts:")
        for symbol in ['SPY', 'QQQ']:
            try:
                stock = Stock(symbol, 'SMART', 'USD')
                details = ib.reqContractDetails(stock)
                if details:
                    print(f"✓ {symbol} works")
            except Exception as e:
                print(f"✗ {symbol} failed: {e}")
        
    finally:
        ib.disconnect()
        print("\nDisconnected")

if __name__ == '__main__':
    sys.exit(main())