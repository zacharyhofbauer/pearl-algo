from __future__ import annotations

from pathlib import Path

from pearlalgo.config.config_loader import load_service_config


def test_load_service_config_merges_defaults(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
service:
  status_update_interval: 123
circuit_breaker:
  max_consecutive_errors: 77
data:
  buffer_size: 42
  stale_data_threshold_minutes: 2
"""
    )

    loaded = load_service_config(cfg)

    # Overrides
    assert loaded["service"]["status_update_interval"] == 123
    assert loaded["circuit_breaker"]["max_consecutive_errors"] == 77
    assert loaded["data"]["buffer_size"] == 42
    assert loaded["data"]["stale_data_threshold_minutes"] == 2

    # Defaults remain for unspecified keys
    assert loaded["service"]["heartbeat_interval"] == 3600
    assert loaded["circuit_breaker"]["max_connection_failures"] == 10
    assert loaded["signals"]["min_confidence"] == 0.50













