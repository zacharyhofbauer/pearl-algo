from __future__ import annotations

from pearlalgo.market_agent.trading_circuit_breaker import (
    TradingCircuitBreaker,
    TradingCircuitBreakerConfig,
)


def test_warn_only_records_would_block() -> None:
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(mode="warn_only"))
    cb.record_would_block("max_consecutive_losses")

    status = cb.get_status()
    assert status["mode"] == "warn_only"
    assert status["would_block_total"] == 1
    assert status["would_block_by_reason"]["max_consecutive_losses"] == 1


def test_invalid_mode_warns() -> None:
    cb = TradingCircuitBreaker(TradingCircuitBreakerConfig(mode="invalid"))
    warnings = cb.validate_config()
    assert any("mode=" in w for w in warnings)
