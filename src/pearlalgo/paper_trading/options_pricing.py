"""
Options Pricing Utilities using Black-Scholes.

Provides Greeks and theoretical pricing for options validation.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from vollib.black_scholes import black_scholes
    from vollib.black_scholes.greeks.analytical import (
        delta,
        gamma,
        rho,
        theta,
        vega,
    )

    HAS_VOLLIB = True
except ImportError:
    HAS_VOLLIB = False
    logging.warning(
        "py-vollib not installed. Options pricing features will be limited."
    )

logger = logging.getLogger(__name__)


class OptionsPricer:
    """
    Options pricing using Black-Scholes model.

    Calculates theoretical prices and Greeks for options validation.
    """

    def __init__(self, risk_free_rate: float = 0.05):
        """
        Initialize options pricer.

        Args:
            risk_free_rate: Risk-free interest rate (default 5%)
        """
        if not HAS_VOLLIB:
            raise ImportError(
                "py-vollib is required for options pricing. "
                "Install with: pip install py-vollib"
            )

        self.risk_free_rate = risk_free_rate

    def calculate_price(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiration: float,  # in years
        implied_volatility: float,
        option_type: str,  # "call" or "put"
    ) -> float:
        """
        Calculate theoretical option price using Black-Scholes.

        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiration: Time to expiration in years
            implied_volatility: Implied volatility (e.g., 0.20 for 20%)
            option_type: "call" or "put"

        Returns:
            Theoretical option price
        """
        flag = "c" if option_type.lower() == "call" else "p"

        try:
            price = black_scholes(
                flag=flag,
                S=underlying_price,
                K=strike,
                t=time_to_expiration,
                r=self.risk_free_rate,
                sigma=implied_volatility,
            )
            return price
        except Exception as e:
            logger.error(f"Error calculating option price: {e}")
            return 0.0

    def calculate_greeks(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiration: float,
        implied_volatility: float,
        option_type: str,
    ) -> dict[str, float]:
        """
        Calculate option Greeks.

        Args:
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiration: Time to expiration in years
            implied_volatility: Implied volatility
            option_type: "call" or "put"

        Returns:
            Dict with delta, gamma, theta, vega, rho
        """
        flag = "c" if option_type.lower() == "call" else "p"

        try:
            greeks = {
                "delta": delta(
                    flag, underlying_price, strike, time_to_expiration, self.risk_free_rate, implied_volatility
                ),
                "gamma": gamma(
                    flag, underlying_price, strike, time_to_expiration, self.risk_free_rate, implied_volatility
                ),
                "theta": theta(
                    flag, underlying_price, strike, time_to_expiration, self.risk_free_rate, implied_volatility
                ),
                "vega": vega(
                    flag, underlying_price, strike, time_to_expiration, self.risk_free_rate, implied_volatility
                ),
                "rho": rho(
                    flag, underlying_price, strike, time_to_expiration, self.risk_free_rate, implied_volatility
                ),
            }
            return greeks
        except Exception as e:
            logger.error(f"Error calculating Greeks: {e}")
            return {
                "delta": 0.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0,
            }

    def validate_price(
        self,
        market_price: float,
        underlying_price: float,
        strike: float,
        time_to_expiration: float,
        implied_volatility: float,
        option_type: str,
        tolerance: float = 0.10,  # 10% tolerance
    ) -> tuple[bool, float]:
        """
        Validate market price against theoretical price.

        Args:
            market_price: Observed market price
            underlying_price: Current underlying price
            strike: Strike price
            time_to_expiration: Time to expiration in years
            implied_volatility: Implied volatility
            option_type: "call" or "put"
            tolerance: Price difference tolerance (default 10%)

        Returns:
            Tuple of (is_valid, theoretical_price)
        """
        theoretical_price = self.calculate_price(
            underlying_price=underlying_price,
            strike=strike,
            time_to_expiration=time_to_expiration,
            implied_volatility=implied_volatility,
            option_type=option_type,
        )

        if theoretical_price == 0:
            return False, 0.0

        price_diff = abs(market_price - theoretical_price) / theoretical_price
        is_valid = price_diff <= tolerance

        if not is_valid:
            logger.debug(
                f"Price validation failed: market={market_price:.2f}, "
                f"theoretical={theoretical_price:.2f}, diff={price_diff:.2%}"
            )

        return is_valid, theoretical_price

