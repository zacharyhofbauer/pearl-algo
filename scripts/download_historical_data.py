#!/usr/bin/env python3
"""
Historical Data Download Script

Downloads historical market data from configured providers and stores
in local Parquet format for deterministic backtesting.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pearlalgo.data_providers.factory import create_data_provider
from pearlalgo.data_providers.normalizer import DataNormalizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config/data_providers.yaml") -> dict:
    """Load data provider configuration."""
    config_file = Path(config_path)
    if not config_file.exists():
        logger.warning(
            f"Config file not found: {config_path}, using defaults"
        )
        return {}

    with open(config_file) as f:
        config = yaml.safe_load(f) or {}
    return config


async def download_symbol_data(
    symbol: str,
    provider_name: str,
    start_date: datetime,
    end_date: datetime,
    timeframe: str = "15m",
    save_to_parquet: bool = True,
    parquet_dir: str = "data/historical",
) -> bool:
    """
    Download historical data for a symbol.

    Args:
        symbol: Ticker symbol
        provider_name: Data provider name
        start_date: Start date
        end_date: End date
        timeframe: Timeframe (e.g., '15m', '1d')
        save_to_parquet: Whether to save to Parquet
        parquet_dir: Directory for Parquet files

    Returns:
        True if successful
    """
    try:
        logger.info(
            f"Downloading {symbol} from {provider_name} "
            f"({start_date.date()} to {end_date.date()}, {timeframe})"
        )

        # Create provider
        provider = create_data_provider(provider_name)

        # Fetch historical data
        if hasattr(provider, "fetch_historical"):
            df = provider.fetch_historical(
                symbol=symbol, start=start_date, end=end_date, timeframe=timeframe
            )
        else:
            logger.error(
                f"Provider {provider_name} does not support fetch_historical"
            )
            return False

        if df.empty:
            logger.warning(f"No data retrieved for {symbol}")
            return False

        # Normalize data
        normalizer = DataNormalizer()
        df_normalized = normalizer.normalize_ohlcv(df)

        if not normalizer.validate_ohlcv(df_normalized):
            logger.error(f"Invalid data format for {symbol}")
            return False

        logger.info(f"Retrieved {len(df_normalized)} rows for {symbol}")

        # Save to Parquet
        if save_to_parquet:
            from pearlalgo.data_providers.local_parquet_provider import (
                LocalParquetProvider,
            )

            parquet_provider = LocalParquetProvider(root_dir=parquet_dir)
            success = parquet_provider.save_historical(
                df=df_normalized,
                symbol=symbol,
                timeframe=timeframe,
                overwrite=True,
            )

            if success:
                logger.info(
                    f"Saved {symbol} data to Parquet "
                    f"({len(df_normalized)} rows)"
                )
            else:
                logger.error(f"Failed to save {symbol} to Parquet")
                return False

        # Close provider if needed
        if hasattr(provider, "close"):
            if asyncio.iscoroutinefunction(provider.close):
                await provider.close()
            else:
                provider.close()

        return True

    except Exception as e:
        logger.error(f"Error downloading {symbol}: {e}", exc_info=True)
        return False


async def download_multiple_symbols(
    symbols: list[str],
    provider_name: str,
    start_date: datetime,
    end_date: datetime,
    timeframe: str = "15m",
    parquet_dir: str = "data/historical",
    delay_between_symbols: float = 1.0,
) -> dict:
    """
    Download historical data for multiple symbols.

    Args:
        symbols: List of ticker symbols
        provider_name: Data provider name
        start_date: Start date
        end_date: End date
        timeframe: Timeframe
        parquet_dir: Directory for Parquet files
        delay_between_symbols: Delay between downloads (seconds)

    Returns:
        Dict with results per symbol
    """
    results = {}
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        logger.info(f"Processing {symbol} ({i}/{total})")

        success = await download_symbol_data(
            symbol=symbol,
            provider_name=provider_name,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            save_to_parquet=True,
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
        description="Download historical market data"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Symbols to download (e.g., QQQ SPY AAPL)",
    )
    parser.add_argument(
        "--provider",
        default="polygon",
        help="Data provider (polygon, tradier, etc.)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD), default: 1 year ago",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date (YYYY-MM-DD), default: today",
    )
    parser.add_argument(
        "--timeframe",
        default="15m",
        help="Timeframe (1m, 5m, 15m, 1h, 1d)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/historical",
        help="Output directory for Parquet files",
    )
    parser.add_argument(
        "--config",
        default="config/data_providers.yaml",
        help="Data provider config file",
    )

    args = parser.parse_args()

    # Parse dates
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    else:
        start_date = datetime.now(timezone.utc) - timedelta(days=365)

    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    else:
        end_date = datetime.now(timezone.utc)

    logger.info(f"Downloading data from {start_date.date()} to {end_date.date()}")

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download data
    results = asyncio.run(
        download_multiple_symbols(
            symbols=args.symbols,
            provider_name=args.provider,
            start_date=start_date,
            end_date=end_date,
            timeframe=args.timeframe,
            parquet_dir=str(output_dir),
        )
    )

    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("Download Summary")
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





