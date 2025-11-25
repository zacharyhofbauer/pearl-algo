from pearlalgo.data.options_utils import black_scholes_greeks, days_to_expiry_from_str


def test_days_to_expiry():
    days = days_to_expiry_from_str("20250101", current_yyyymmdd="20241231")
    assert days == 1


def test_greeks_call_basic():
    greeks = black_scholes_greeks(spot=100, strike=100, days_to_expiry=30, rate=0.0, vol=0.2, right="C")
    assert "delta" in greeks and 0 < greeks["delta"] < 1
