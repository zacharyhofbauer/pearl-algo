"""Technical indicator calculations for candle data.

Provides ``calculate_indicators`` which computes EMA, VWAP, Bollinger Bands,
ATR Bands, and Volume Profile from a list of OHLCV candle dictionaries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def calculate_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate EMA, VWAP, Bollinger Bands, ATR Bands, and Volume Profile from candle data."""
    if not candles:
        return {
            "ema9": [], "ema21": [], "vwap": [],
            "bollingerBands": [], "atrBands": [], "volumeProfile": None
        }

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    opens = [c["open"] for c in candles]
    volumes = [c.get("volume", 1000) for c in candles]
    times = [c["time"] for c in candles]

    # EMA calculation
    def ema(data, period):
        result = []
        multiplier = 2 / (period + 1)
        ema_val = sum(data[:period]) / period if len(data) >= period else data[0]
        for i, val in enumerate(data):
            if i < period - 1:
                result.append(None)
            elif i == period - 1:
                result.append(ema_val)
            else:
                ema_val = (val - ema_val) * multiplier + ema_val
                result.append(ema_val)
        return result

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)

    # VWAP calculation (simplified - cumulative)
    vwap = []
    cum_vol_price = 0
    cum_vol = 0
    for i, c in enumerate(candles):
        typical_price = (highs[i] + lows[i] + closes[i]) / 3
        cum_vol_price += typical_price * volumes[i]
        cum_vol += volumes[i]
        vwap.append(cum_vol_price / cum_vol if cum_vol > 0 else typical_price)

    # Bollinger Bands (20 SMA, 2 std dev)
    def calculate_bollinger_bands(data, period=20, num_std=2):
        result = []
        for i in range(len(data)):
            if i < period - 1:
                result.append(None)
            else:
                window = data[i - period + 1:i + 1]
                sma = sum(window) / period
                variance = sum((x - sma) ** 2 for x in window) / period
                std = variance ** 0.5
                result.append({
                    "upper": sma + (num_std * std),
                    "middle": sma,
                    "lower": sma - (num_std * std)
                })
        return result

    bb_values = calculate_bollinger_bands(closes)

    # ATR Bands (14-period ATR, 2x multiplier)
    def calculate_atr_bands(highs, lows, closes, period=14, multiplier=2):
        # Calculate True Range
        true_ranges = []
        for i in range(len(closes)):
            if i == 0:
                tr = highs[i] - lows[i]
            else:
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i-1]),
                    abs(lows[i] - closes[i-1])
                )
            true_ranges.append(tr)

        # Calculate ATR using EMA
        atr_values = []
        atr = 0
        for i in range(len(closes)):
            if i < period - 1:
                atr_values.append(None)
            elif i == period - 1:
                atr = sum(true_ranges[:period]) / period
                atr_values.append(atr)
            else:
                atr = ((atr * (period - 1)) + true_ranges[i]) / period
                atr_values.append(atr)

        # Calculate bands around typical price
        result = []
        for i in range(len(closes)):
            if atr_values[i] is not None:
                typical_price = (highs[i] + lows[i] + closes[i]) / 3
                result.append({
                    "upper": typical_price + (multiplier * atr_values[i]),
                    "lower": typical_price - (multiplier * atr_values[i]),
                    "atr": atr_values[i]
                })
            else:
                result.append(None)
        return result

    atr_bands = calculate_atr_bands(highs, lows, closes)

    # Volume Profile calculation
    def calculate_volume_profile(candles, num_levels=50, value_area_pct=0.70):
        if not candles:
            return None

        max_price = max(highs)
        min_price = min(lows)
        price_range = max_price - min_price
        if price_range == 0:
            return None

        level_height = price_range / num_levels

        # Initialize levels
        levels = {}
        for i in range(num_levels):
            level_price = min_price + (level_height * i) + (level_height / 2)
            level_price = round(level_price, 2)
            levels[level_price] = {"volume": 0, "buyVolume": 0, "sellVolume": 0}

        # Distribute volume to price levels
        for i, c in enumerate(candles):
            vol = volumes[i]
            is_bullish = closes[i] >= opens[i]
            candle_high = highs[i]
            candle_low = lows[i]

            for price, level_data in levels.items():
                if candle_low <= price <= candle_high:
                    # Distribute volume proportionally
                    candle_range = candle_high - candle_low
                    if candle_range > 0:
                        level_vol = vol / (candle_range / level_height)
                    else:
                        level_vol = vol / num_levels

                    level_data["volume"] += level_vol
                    if is_bullish:
                        level_data["buyVolume"] += level_vol * 0.6
                        level_data["sellVolume"] += level_vol * 0.4
                    else:
                        level_data["buyVolume"] += level_vol * 0.4
                        level_data["sellVolume"] += level_vol * 0.6

        # Find POC (Point of Control - highest volume level)
        poc = min_price
        max_vol = 0
        for price, data in levels.items():
            if data["volume"] > max_vol:
                max_vol = data["volume"]
                poc = price

        # Calculate Value Area (70% of volume)
        total_volume = sum(d["volume"] for d in levels.values())
        target_volume = total_volume * value_area_pct

        sorted_prices = sorted(levels.keys())
        poc_index = sorted_prices.index(poc) if poc in sorted_prices else len(sorted_prices) // 2

        cum_volume = levels.get(poc, {}).get("volume", 0)
        vah_index = poc_index
        val_index = poc_index

        while cum_volume < target_volume:
            upper_vol = levels.get(sorted_prices[vah_index + 1], {}).get("volume", 0) if vah_index < len(sorted_prices) - 1 else 0
            lower_vol = levels.get(sorted_prices[val_index - 1], {}).get("volume", 0) if val_index > 0 else 0

            if upper_vol >= lower_vol and vah_index < len(sorted_prices) - 1:
                vah_index += 1
                cum_volume += levels[sorted_prices[vah_index]]["volume"]
            elif val_index > 0:
                val_index -= 1
                cum_volume += levels[sorted_prices[val_index]]["volume"]
            else:
                break

        vah = sorted_prices[vah_index] if vah_index < len(sorted_prices) else max_price
        val = sorted_prices[val_index] if val_index >= 0 else min_price

        # Format levels for response
        levels_list = [
            {
                "price": price,
                "volume": round(data["volume"]),
                "buyVolume": round(data["buyVolume"]),
                "sellVolume": round(data["sellVolume"])
            }
            for price, data in levels.items()
            if data["volume"] > 0
        ]

        return {
            "levels": sorted(levels_list, key=lambda x: x["price"]),
            "poc": round(poc, 2),
            "vah": round(vah, 2),
            "val": round(val, 2)
        }

    volume_profile = calculate_volume_profile(candles)

    # Format Bollinger Bands data
    bb_data = [
        {
            "time": times[i],
            "upper": round(bb["upper"], 2),
            "middle": round(bb["middle"], 2),
            "lower": round(bb["lower"], 2)
        }
        for i, bb in enumerate(bb_values) if bb is not None
    ]

    # Format ATR Bands data
    atr_data = [
        {
            "time": times[i],
            "upper": round(atr["upper"], 2),
            "lower": round(atr["lower"], 2),
            "atr": round(atr["atr"], 2)
        }
        for i, atr in enumerate(atr_bands) if atr is not None
    ]

    # Format for TradingView
    return {
        "ema9": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema9) if v is not None],
        "ema21": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(ema21) if v is not None],
        "vwap": [{"time": times[i], "value": round(v, 2)} for i, v in enumerate(vwap)],
        "bollingerBands": bb_data,
        "atrBands": atr_data,
        "volumeProfile": volume_profile,
    }
