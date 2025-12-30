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


# =============================================================================
# ATS CONFIG TESTS - execution and learning sections
# =============================================================================


def test_load_service_config_includes_execution_section(tmp_path: Path) -> None:
    """Verify execution config section is returned with safe defaults."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("service:\n  status_update_interval: 100\n")

    loaded = load_service_config(cfg)

    # Execution section must exist
    assert "execution" in loaded
    exec_cfg = loaded["execution"]

    # Safety defaults: disabled, disarmed, dry_run mode
    assert exec_cfg["enabled"] is False
    assert exec_cfg["armed"] is False
    assert exec_cfg["mode"] == "dry_run"

    # Risk limits have safe defaults
    assert exec_cfg["max_positions"] == 1
    assert exec_cfg["max_orders_per_day"] == 20
    assert exec_cfg["max_daily_loss"] == 500.0
    assert exec_cfg["cooldown_seconds"] == 60

    # Symbol whitelist defaults to MNQ
    assert exec_cfg["symbol_whitelist"] == ["MNQ"]


def test_load_service_config_includes_learning_section(tmp_path: Path) -> None:
    """Verify learning config section is returned with safe defaults."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("service:\n  status_update_interval: 100\n")

    loaded = load_service_config(cfg)

    # Learning section must exist
    assert "learning" in loaded
    learn_cfg = loaded["learning"]

    # Default enabled, shadow mode (safe - no effect on execution)
    assert learn_cfg["enabled"] is True
    assert learn_cfg["mode"] == "shadow"

    # Bandit parameters have sensible defaults
    assert learn_cfg["min_samples_per_type"] == 10
    assert learn_cfg["explore_rate"] == 0.1
    assert learn_cfg["decision_threshold"] == 0.3
    assert learn_cfg["prior_alpha"] == 2.0
    assert learn_cfg["prior_beta"] == 2.0


def test_load_service_config_merges_execution_overrides(tmp_path: Path) -> None:
    """Verify execution config overrides merge with defaults."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
execution:
  enabled: true
  mode: paper
  max_positions: 3
"""
    )

    loaded = load_service_config(cfg)
    exec_cfg = loaded["execution"]

    # Overrides applied
    assert exec_cfg["enabled"] is True
    assert exec_cfg["mode"] == "paper"
    assert exec_cfg["max_positions"] == 3

    # Non-overridden values stay at defaults
    assert exec_cfg["armed"] is False  # Safety default preserved
    assert exec_cfg["max_daily_loss"] == 500.0


def test_load_service_config_merges_learning_overrides(tmp_path: Path) -> None:
    """Verify learning config overrides merge with defaults."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
learning:
  mode: live
  decision_threshold: 0.5
  min_samples_per_type: 20
"""
    )

    loaded = load_service_config(cfg)
    learn_cfg = loaded["learning"]

    # Overrides applied
    assert learn_cfg["mode"] == "live"
    assert learn_cfg["decision_threshold"] == 0.5
    assert learn_cfg["min_samples_per_type"] == 20

    # Non-overridden values stay at defaults
    assert learn_cfg["enabled"] is True
    assert learn_cfg["explore_rate"] == 0.1













