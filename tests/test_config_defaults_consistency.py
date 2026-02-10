"""
Tests that defaults.py and config_schema.py stay consistent.

If someone edits a default constant or renames it without updating the
corresponding Pydantic model (or vice-versa), these tests will catch the
mismatch at CI time.

Covers:
- All ``defaults.X`` references in config_schema.py actually exist in defaults.py
- A FullServiceConfig() instantiated with no arguments has key fields whose
  values match the canonical defaults.py constants
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from pearlalgo.config import defaults
from pearlalgo.config.config_schema import FullServiceConfig, validate_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_defaults_references(source: str) -> list[str]:
    """Parse *source* and return every ``defaults.ATTR`` attribute name used."""
    tree = ast.parse(source)
    refs: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "defaults"
        ):
            refs.append(node.attr)
    return refs


# ---------------------------------------------------------------------------
# 1. Every ``defaults.X`` reference in config_schema.py exists in defaults.py
# ---------------------------------------------------------------------------

class TestDefaultsReferencesExist:
    """Verify every ``defaults.X`` used in config_schema.py is a real constant."""

    @pytest.fixture(scope="class")
    def schema_source(self) -> str:
        src_path = Path(inspect.getfile(FullServiceConfig)).resolve()
        return src_path.read_text()

    @pytest.fixture(scope="class")
    def referenced_attrs(self, schema_source: str) -> list[str]:
        return _extract_defaults_references(schema_source)

    def test_at_least_one_reference_found(self, referenced_attrs: list[str]) -> None:
        """Sanity-check: the parser should find many defaults.X references."""
        assert len(referenced_attrs) > 0, "No defaults.X references found — parser broken?"

    def test_each_reference_exists_in_defaults_module(
        self, referenced_attrs: list[str]
    ) -> None:
        """Every ``defaults.ATTR`` used in config_schema.py must exist."""
        missing = [attr for attr in referenced_attrs if not hasattr(defaults, attr)]
        assert missing == [], (
            f"config_schema.py references defaults that do not exist: {missing}"
        )


# ---------------------------------------------------------------------------
# 2. FullServiceConfig() default field values match defaults.py constants
# ---------------------------------------------------------------------------

class TestFullServiceConfigMatchesDefaults:
    """
    Instantiate ``FullServiceConfig()`` with zero arguments and confirm that
    key fields have values identical to the corresponding ``defaults.py``
    constants.

    This catches silent divergence — e.g. someone changes the Pydantic default
    literal without updating ``defaults.py`` (or the reverse).
    """

    @pytest.fixture(scope="class")
    def cfg(self) -> FullServiceConfig:
        return FullServiceConfig()

    # -- ServiceConfig section ------------------------------------------

    def test_status_update_interval(self, cfg: FullServiceConfig) -> None:
        assert cfg.service.status_update_interval == defaults.STATUS_UPDATE_INTERVAL

    def test_heartbeat_interval(self, cfg: FullServiceConfig) -> None:
        assert cfg.service.heartbeat_interval == defaults.HEARTBEAT_INTERVAL

    def test_state_save_interval(self, cfg: FullServiceConfig) -> None:
        assert cfg.service.state_save_interval == defaults.STATE_SAVE_INTERVAL

    def test_dashboard_chart_enabled(self, cfg: FullServiceConfig) -> None:
        assert cfg.service.dashboard_chart_enabled == defaults.DASHBOARD_CHART_ENABLED

    def test_enable_new_bar_gating(self, cfg: FullServiceConfig) -> None:
        assert cfg.service.enable_new_bar_gating == defaults.ENABLE_NEW_BAR_GATING

    # -- RiskConfig section ---------------------------------------------

    def test_max_risk_per_trade(self, cfg: FullServiceConfig) -> None:
        assert cfg.risk.max_risk_per_trade == defaults.MAX_RISK_PER_TRADE

    def test_stop_loss_atr_multiplier(self, cfg: FullServiceConfig) -> None:
        assert cfg.risk.stop_loss_atr_multiplier == defaults.STOP_LOSS_ATR_MULTIPLIER

    # -- DataConfig section ---------------------------------------------

    def test_data_buffer_size(self, cfg: FullServiceConfig) -> None:
        assert cfg.data.buffer_size == defaults.DATA_BUFFER_SIZE

    def test_historical_hours(self, cfg: FullServiceConfig) -> None:
        assert cfg.data.historical_hours == defaults.HISTORICAL_HOURS

    def test_enable_mtf_cache(self, cfg: FullServiceConfig) -> None:
        assert cfg.data.enable_mtf_cache == defaults.ENABLE_MTF_CACHE

    # -- SignalsConfig section ------------------------------------------

    def test_min_confidence(self, cfg: FullServiceConfig) -> None:
        assert cfg.signals.min_confidence == defaults.MIN_CONFIDENCE

    def test_duplicate_window_seconds(self, cfg: FullServiceConfig) -> None:
        assert cfg.signals.duplicate_window_seconds == defaults.DUPLICATE_WINDOW_SECONDS

    # -- CircuitBreakerConfig section -----------------------------------

    def test_max_consecutive_errors(self, cfg: FullServiceConfig) -> None:
        assert cfg.circuit_breaker.max_consecutive_errors == defaults.MAX_CONSECUTIVE_ERRORS

    # -- StorageConfig section ------------------------------------------

    def test_storage_sqlite_enabled(self, cfg: FullServiceConfig) -> None:
        assert cfg.storage.sqlite_enabled == defaults.STORAGE_SQLITE_ENABLED

    def test_storage_db_path(self, cfg: FullServiceConfig) -> None:
        assert cfg.storage.db_path == defaults.STORAGE_DB_PATH

    # -- ChallengeConfig section ----------------------------------------

    def test_challenge_enabled(self, cfg: FullServiceConfig) -> None:
        assert cfg.challenge.enabled == defaults.CHALLENGE_ENABLED

    def test_challenge_start_balance(self, cfg: FullServiceConfig) -> None:
        assert cfg.challenge.start_balance == defaults.CHALLENGE_START_BALANCE

    # -- PerformanceConfig section --------------------------------------

    def test_performance_max_records(self, cfg: FullServiceConfig) -> None:
        assert cfg.performance.max_records == defaults.PERFORMANCE_MAX_RECORDS

    # -- TelegramUIConfig section ---------------------------------------

    def test_telegram_ui_compact_metrics(self, cfg: FullServiceConfig) -> None:
        assert cfg.telegram_ui.compact_metrics_enabled == defaults.TELEGRAM_UI_COMPACT_METRICS


# ---------------------------------------------------------------------------
# 3. validate_config({}) round-trip also matches defaults
# ---------------------------------------------------------------------------

class TestValidateConfigEmptyDict:
    """``validate_config({})`` should produce the same defaults."""

    def test_roundtrip_matches_direct_instantiation(self) -> None:
        from_dict = validate_config({})
        direct = FullServiceConfig()
        # Compare a representative subset
        assert from_dict.service.status_update_interval == direct.service.status_update_interval
        assert from_dict.risk.max_risk_per_trade == direct.risk.max_risk_per_trade
        assert from_dict.data.buffer_size == direct.data.buffer_size
        assert from_dict.signals.min_confidence == direct.signals.min_confidence
        assert from_dict.storage.sqlite_enabled == direct.storage.sqlite_enabled
