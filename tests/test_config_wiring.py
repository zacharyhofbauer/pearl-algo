from __future__ import annotations

from pathlib import Path

import pytest

from pearlalgo.nq_agent.data_fetcher import NQAgentDataFetcher
from pearlalgo.nq_agent.service import NQAgentService
from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
from tests.mock_data_provider import MockDataProvider


def test_service_wires_service_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pearlalgo.nq_agent.service as service_mod

    fake = {
        "service": {
            "status_update_interval": 111,
            "heartbeat_interval": 222,
            "state_save_interval": 3,
            "connection_failure_alert_interval": 44,
            "data_quality_alert_interval": 55,
        },
        "circuit_breaker": {
            "max_consecutive_errors": 6,
            "max_connection_failures": 7,
            "max_data_fetch_errors": 8,
        },
        "data": {
            "stale_data_threshold_minutes": 9,
            "connection_timeout_minutes": 10,
        },
    }

    monkeypatch.setattr(service_mod, "load_service_config", lambda: fake)

    provider = MockDataProvider(simulate_delayed_data=False, simulate_timeouts=False, simulate_connection_issues=False)
    svc = NQAgentService(data_provider=provider, config=NQIntradayConfig(), state_dir=tmp_path)

    assert svc.status_update_interval == 111
    assert svc.heartbeat_interval == 222
    assert svc.state_save_interval == 3
    assert svc.connection_failure_alert_interval == 44
    assert svc.data_quality_alert_interval == 55
    assert svc.max_consecutive_errors == 6
    assert svc.max_connection_failures == 7
    assert svc.max_data_fetch_errors == 8
    assert svc.stale_data_threshold_minutes == 9
    assert svc.connection_timeout_minutes == 10


def test_data_fetcher_wires_data_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import pearlalgo.nq_agent.data_fetcher as fetcher_mod

    fake = {
        "data": {
            "buffer_size": 12,
            "buffer_size_5m": 4,
            "buffer_size_15m": 3,
            "historical_hours": 1,
            "multitimeframe_5m_hours": 2,
            "multitimeframe_15m_hours": 6,
            "stale_data_threshold_minutes": 1,
        }
    }
    monkeypatch.setattr(fetcher_mod, "load_service_config", lambda: fake)

    provider = MockDataProvider(simulate_delayed_data=False, simulate_timeouts=False, simulate_connection_issues=False)
    fetcher = NQAgentDataFetcher(provider, config=NQIntradayConfig())

    assert fetcher._buffer_size == 12  # noqa: SLF001 - wiring test
    assert fetcher._buffer_size_5m == 4  # noqa: SLF001 - wiring test
    assert fetcher._buffer_size_15m == 3  # noqa: SLF001 - wiring test
    assert fetcher._historical_hours == 1  # noqa: SLF001 - wiring test
    assert fetcher._multitimeframe_5m_hours == 2  # noqa: SLF001 - wiring test
    assert fetcher._multitimeframe_15m_hours == 6  # noqa: SLF001 - wiring test
    assert fetcher.stale_data_threshold_minutes == 1




