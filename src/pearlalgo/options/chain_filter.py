"""
Options Chain Filter - Filter options by liquidity, strike, expiration.

Provides:
- Filter by liquidity (volume, open interest)
- Strike selection (ATM, OTM, ITM)
- Expiration filtering (near-term, weekly)
- IV rank thresholds
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    from loguru import logger as loguru_logger

    logger = loguru_logger
except ImportError:
    logger = logging.getLogger(__name__)


class OptionsChainFilter:
    """
    Filter options chains based on various criteria.

    Filters by:
    - Liquidity (volume, open interest)
    - Strike selection (ATM, OTM, ITM)
    - Expiration (days to expiration)
    - IV rank thresholds
    """

    def __init__(
        self,
        min_volume: int = 100,
        min_open_interest: int = 50,
        max_dte: int = 45,
        min_iv_rank: float = 20.0,
        strike_selection: str = "atm",  # "atm", "otm", "itm"
    ):
        """
        Initialize options chain filter.

        Args:
            min_volume: Minimum volume threshold
            min_open_interest: Minimum open interest threshold
            max_dte: Maximum days to expiration
            min_iv_rank: Minimum IV rank (0-100)
            strike_selection: Strike selection method ("atm", "otm", "itm")
        """
        self.min_volume = min_volume
        self.min_open_interest = min_open_interest
        self.max_dte = max_dte
        self.min_iv_rank = min_iv_rank
        self.strike_selection = strike_selection

        logger.info(
            f"OptionsChainFilter initialized: min_volume={min_volume}, "
            f"min_oi={min_open_interest}, max_dte={max_dte}, "
            f"min_iv_rank={min_iv_rank}, strike={strike_selection}"
        )

    def filter_chain(
        self,
        chain: List[Dict],
        underlying_price: float,
        current_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Filter options chain based on criteria.

        Args:
            chain: List of option contracts (from Polygon API)
            underlying_price: Current underlying price
            current_date: Current date (default: now)

        Returns:
            Filtered list of option contracts
        """
        if current_date is None:
            current_date = datetime.now(timezone.utc)

        filtered = []

        for option in chain:
            # Filter by volume
            volume = option.get("volume", 0)
            if volume < self.min_volume:
                continue

            # Filter by open interest
            open_interest = option.get("open_interest", 0)
            if open_interest < self.min_open_interest:
                continue

            # Filter by days to expiration
            expiration = option.get("expiration_date")
            if expiration:
                if isinstance(expiration, str):
                    try:
                        exp_date = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
                    except Exception:
                        continue
                else:
                    exp_date = expiration

                dte = (exp_date - current_date).days
                if dte > self.max_dte:
                    continue

            # Filter by IV rank (if available)
            iv_rank = option.get("iv_rank")
            if iv_rank is not None and iv_rank < self.min_iv_rank:
                continue

            # Filter by strike selection
            strike = option.get("strike_price")
            if strike:
                if self.strike_selection == "atm":
                    # At-the-money: within 5% of underlying
                    if abs(strike - underlying_price) / underlying_price > 0.05:
                        continue
                elif self.strike_selection == "otm":
                    # Out-of-the-money: calls above, puts below
                    option_type = option.get("option_type", "").lower()
                    if option_type == "call" and strike <= underlying_price:
                        continue
                    if option_type == "put" and strike >= underlying_price:
                        continue
                elif self.strike_selection == "itm":
                    # In-the-money: calls below, puts above
                    option_type = option.get("option_type", "").lower()
                    if option_type == "call" and strike >= underlying_price:
                        continue
                    if option_type == "put" and strike <= underlying_price:
                        continue

            filtered.append(option)

        logger.debug(
            f"Filtered options chain: {len(chain)} -> {len(filtered)} contracts"
        )
        return filtered

    def select_best_option(
        self,
        chain: List[Dict],
        underlying_price: float,
        prefer_calls: bool = True,
    ) -> Optional[Dict]:
        """
        Select the best option from filtered chain.

        Args:
            chain: Filtered options chain
            underlying_price: Current underlying price
            prefer_calls: Prefer calls over puts (default: True)

        Returns:
            Best option contract or None
        """
        if not chain:
            return None

        # Sort by volume * open interest (liquidity score)
        scored = []
        for option in chain:
            volume = option.get("volume", 0)
            oi = option.get("open_interest", 0)
            liquidity_score = volume * oi

            option_type = option.get("option_type", "").lower()
            is_call = option_type == "call"

            scored.append((liquidity_score, is_call, option))

        # Sort by liquidity (descending), then prefer calls/puts
        scored.sort(key=lambda x: (x[0], x[1] == prefer_calls), reverse=True)

        return scored[0][2] if scored else None
