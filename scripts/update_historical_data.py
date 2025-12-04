#!/usr/bin/env python3
"""
Historical Data Update Script

Updates existing historical data by appending new data from the latest
available date in storage to today.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.data_providers.local_parquet_provider import LocalParquetProvider
from pearlalgo.data_providers.normalizer import DataNormalizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def update_symbol_data(
    symbol: str,
    provider_name: str,
    timeframe: str = "15m",
    parquet_dir: str = "data/historical",
) -> bool:
    """
    Update historical data for a symbol by appending new data.

    Args:
        symbol: Ticker symbol
        provider_name: Data provider name
        timeframe: Timeframe
        parquet_dir: Directory for Parquet files

    Returns:
        True if successful
    """
    try:
        parquet_provider = LocalParquetProvider(root_dir=parquet_dir)

        # Check if file exists
        if not parquet_provider.file_exists(symbol, timeframe):
            logger.warning(
                f"No existing data found for {symbol} ({timeframe}). "
                f"Use download_historical_data.py to create initial dataset."
            )
            return False

        # Load existing data to find last date
        existing_df = parquet_provider.fetch_historical(
            symbol=symbol, timeframe=timeframe
        )

        if existing_df.empty:
            logger.warning(f"Existing data file is empty for {symbol}")
            return False

        last_date = existing_df.index.max()
        start_date = last_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + pd.Timedelta(days=1)
        end_date = datetime.now(timezone.utc)

        logger.info(
            f"Updating {symbol}: fetching data from {start_date.date()} "
            f"to {end_date.date()}"
        )

        # Download new data
        provider = create_data_provider(provider_name)

        if hasattr(provider, "fetch_historical"):
            new_df = provider.fetch_historical(
                symbol=symbol,
                start=start_date,
                end=end_date,
                timeframe=timeframe,
            )
        else:
            logger.error(
                f"Provider {provider_name} does not support fetch_historical"
            )
            return False

        if new_df.empty:
            logger.info(f"No new data available for {symbol}")
            return True

        # Normalize new data
        normalizer = DataNormalizer()
        new_df_normalized = normalizer.normalize_ohlcv(new_df)

        if not normalizer.validate_ohlcv(new_df_normalized):
            logger.error(f"Invalid data format for new {symbol} data")
            return False

        logger.info(f"Retrieved {len(new_df_normalized)} new rows for {symbol}")

        # Combine with existing data
        combined_df = pd.concat([existing_df, new_df_normalized])
        combined_df = combined_df[~combined_df.index.duplicated(keep="last")]
        combined_df.sort_index(inplace=True)

        logger.info(
            f"Combined dataset: {len(existing_df)} existing + "
            f"{len(new_df_normalized)} new = {len(combined_df)} total rows"
        )

        # Save updated data
        success = parquet_provider.save_historical(
            df=combined_df,
            symbol=symbol,
            timeframe=timeframe,
            overwrite=True,
        )

        if success:
            logger.info(f"Updated {symbol} data successfully")
        else:
            logger.error(f"Failed to save updated {symbol} data")
            return False

        # Close provider if needed
        if hasattr(provider, "close"):
            if asyncio.iscoroutinefunction(provider.close):
                await provider.close()
            else:
                provider.close()

        return True

    except Exception as e:
        logger.error(f"Error updating {symbol}: {e}", exc_info=True)
        return False


async def update_multiple_symbols(
    symbols: list[str],
    provider_name: str,
    timeframe: str = "15m",
    parquet_dir: str = "data/historical",
    delay_between_symbols: float = 1.0,
) -> dict:
    """
    Update historical data for multiple symbols.

    Args:
        symbols: List of ticker symbols
        provider_name: Data provider name
        timeframe: Timeframe
        parquet_dir: Directory for Parquet files
        delay_between_symbols: Delay between updates (seconds)

    Returns:
        Dict with results per symbol
    """
    results = {}
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        logger.info(f"Updating {symbol} ({i}/{total})")

        success = await update_symbol_data(
            symbol=symbol,
            provider_name=provider_name,
            timeframe=timeframe,
            parquet_dir=parquet_dir,
        )

        results[symbol] = "success" if success else "failed"

        # Rate limiting between symbols
        if i < total:
            await asyncio.sleep(delay_between_symbols)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Update existing historical market data"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Symbols to update (e.g., QQQ SPY AAPL)",
    )
    parser.add_argument(
        "--provider",
        default="polygon",
        help="Data provider (polygon, tradier, etc.)",
    )
    parser.add_argument(
        "--timeframe",
        default="15m",
        help="Timeframe (1m, 5m, 15m, 1h, 1d)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/historical",
        help="Directory with Parquet files",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Update all symbols found in output directory",
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get symbols to update
    if args.all:
        parquet_provider = LocalParquetProvider(root_dir=str(output_dir))
        symbols = parquet_provider.list_symbols(timeframe=args.timeframe)
        if not symbols:
            logger.warning(f"No symbols found in {output_dir}")
            sys.exit(1)
        logger.info(f"Found {len(symbols)} symbols to update")
    else:
        symbols = args.symbols

    # Update data
    results = asyncio.run(
        update_multiple_symbols(
            symbols=symbols,
            provider_name=args.provider,
            timeframe=args.timeframe,
            parquet_dir=str(output_dir),
        )
    )

    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("Update Summary")
    logger.info("=" * 50)
    successful = sum(1 for v in results.values() if v == "success")
    failed = len(results) - successful

    for symbol, status in results.items():
        logger.info(f"  {symbol}: {status}")

    logger.info(f"\nTotal: {len(results)} symbols")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()




