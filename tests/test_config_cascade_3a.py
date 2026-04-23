"""Tests for Issue 3-A config cascade fixes.

Three narrow fixes bundled (plan:
``~/.claude/plans/this-session-work-cosmic-horizon.md``):

1. **Fix 1 (narrow):** ``signal_generator.CONFIG`` marks ``timeframe`` and
   ``scan_interval`` as legacy in-code defaults; ``generate_signals`` logs
   the effective load-bearing config on first call so drift between the
   in-code defaults and the live YAML cascade is visible.

2. **Fix 2:** ``schema_v2.SignalsConfig.enabled_signal_types`` is validated
   against ``KNOWN_SIGNAL_TYPES``; unknown names (typos, stale triggers)
   are rejected at config-load time instead of silently dropping at
   runtime.

3. **Fix 3:** ``config_file._safe_load_no_duplicates`` rejects duplicate
   YAML mapping keys via ``DuplicateConfigKeyError``. Prevents a
   refactor that accidentally creates two ``strategies.composite_intraday``
   blocks from silently losing one of them.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
import yaml

from pearlalgo.config.config_file import (
    DuplicateConfigKeyError,
    _safe_load_no_duplicates,
)
from pearlalgo.config.schema_v2 import (
    KNOWN_SIGNAL_TYPES,
    SignalsConfig,
    validate_config,
)


# ---------------------------------------------------------------------------
# Fix 3 — YAML duplicate-key detector
# ---------------------------------------------------------------------------


def test_safe_load_no_duplicates_accepts_valid_yaml():
    doc = "a: 1\nb:\n  c: 2\n  d: [x, y]\n"
    result = _safe_load_no_duplicates(io.StringIO(doc))
    assert result == {"a": 1, "b": {"c": 2, "d": ["x", "y"]}}


def test_safe_load_no_duplicates_top_level_duplicate_raises():
    doc = "a: 1\nb: 2\na: 3\n"
    with pytest.raises(DuplicateConfigKeyError) as exc_info:
        _safe_load_no_duplicates(io.StringIO(doc))
    msg = str(exc_info.value)
    assert "'a'" in msg
    assert "line" in msg.lower()


def test_safe_load_no_duplicates_nested_duplicate_raises():
    doc = (
        "strategies:\n"
        "  composite_intraday:\n"
        "    min_confidence: 0.6\n"
        "    stop_loss_atr_mult: 2.5\n"
        "    min_confidence: 0.9\n"  # silent shadow today; loud now
    )
    with pytest.raises(DuplicateConfigKeyError) as exc_info:
        _safe_load_no_duplicates(io.StringIO(doc))
    assert "min_confidence" in str(exc_info.value)


def test_safe_load_no_duplicates_preserves_scalar_types():
    doc = "int_val: 42\nfloat_val: 3.14\nbool_val: true\nnull_val: ~\n"
    result = _safe_load_no_duplicates(io.StringIO(doc))
    assert result["int_val"] == 42
    assert result["float_val"] == 3.14
    assert result["bool_val"] is True
    assert result["null_val"] is None


def test_safe_load_no_duplicates_on_real_live_config():
    """The canonical live YAML must pass the stricter loader as-is."""
    from pearlalgo.utils.paths import get_project_root

    path = get_project_root() / "config" / "live" / "tradovate_paper.yaml"
    with path.open() as handle:
        cfg = _safe_load_no_duplicates(handle)
    assert isinstance(cfg, dict)
    assert cfg.get("account", {}).get("name") == "tradovate_paper"


def test_safe_load_no_duplicates_on_real_base_config():
    """``config/base.yaml`` must also pass the stricter loader."""
    from pearlalgo.utils.paths import get_project_root

    path = get_project_root() / "config" / "base.yaml"
    with path.open() as handle:
        cfg = _safe_load_no_duplicates(handle)
    assert isinstance(cfg, dict)


# ---------------------------------------------------------------------------
# Fix 2 — enabled_signal_types validation against KNOWN_SIGNAL_TYPES
# ---------------------------------------------------------------------------


def test_known_signal_types_matches_canonical_live_yaml_set():
    """The frozen set of valid emitters must cover today's live YAML."""
    live_signals = {
        "pearlbot_pinescript",
        "smc_fvg",
        "smc_ob",
        "smc_silver_bullet",
    }
    assert live_signals.issubset(KNOWN_SIGNAL_TYPES)


def test_signals_config_empty_enabled_signal_types_ok():
    cfg = SignalsConfig()
    assert cfg.enabled_signal_types == []


def test_signals_config_accepts_known_signal_types():
    cfg = SignalsConfig(enabled_signal_types=sorted(KNOWN_SIGNAL_TYPES))
    assert set(cfg.enabled_signal_types) == KNOWN_SIGNAL_TYPES


def test_signals_config_rejects_single_unknown_name():
    with pytest.raises(ValueError) as exc_info:
        SignalsConfig(enabled_signal_types=["pearlbot_pinescript", "typo_strategy"])
    assert "typo_strategy" in str(exc_info.value)
    assert "unknown" in str(exc_info.value).lower()


def test_signals_config_rejects_mixed_unknown_names():
    with pytest.raises(ValueError) as exc_info:
        SignalsConfig(enabled_signal_types=["foo", "bar", "smc_fvg"])
    msg = str(exc_info.value)
    assert "foo" in msg and "bar" in msg


def test_validate_config_accepts_live_yaml_signals():
    """End-to-end: the canonical live YAML must survive schema_v2 validation."""
    from pearlalgo.utils.paths import get_project_root

    path = get_project_root() / "config" / "live" / "tradovate_paper.yaml"
    with path.open() as handle:
        raw = yaml.safe_load(handle)
    validated = validate_config(raw)
    assert set(validated["signals"]["enabled_signal_types"]).issubset(KNOWN_SIGNAL_TYPES)


def test_validate_config_rejects_unknown_signal_name_end_to_end():
    raw: dict[str, Any] = {
        "symbol": "MNQ",
        "timeframe": "1m",
        "scan_interval": 30,
        "signals": {
            "enabled_signal_types": ["pearlbot_pinescript", "not_a_real_trigger"],
        },
    }
    with pytest.raises(Exception) as exc_info:
        validate_config(raw)
    assert "not_a_real_trigger" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Fix 1 (narrow) — signal_generator drift log
# ---------------------------------------------------------------------------


@pytest.fixture
def loguru_sink():
    """Install a temporary loguru sink that records INFO+ messages.

    The project uses ``loguru`` whose default sink goes straight to
    ``sys.stderr`` (bypassing pytest's ``capsys`` / ``caplog``). A
    per-test sink is the cleanest way to assert on log content.
    """
    from pearlalgo.utils.logger import logger

    records: list[str] = []
    sink_id = logger.add(lambda msg: records.append(str(msg)), level="INFO")
    try:
        yield records
    finally:
        logger.remove(sink_id)


def test_generate_signals_logs_effective_timeframe_once(loguru_sink):
    """First call logs the effective timeframe + drift flag; subsequent
    calls do not re-log (hot-loop-safe)."""
    import pearlalgo.trading_bots.signal_generator as sg

    sg._LOGGED_EFFECTIVE_TIMEFRAME = False

    live_config = {"timeframe": "1m", "scan_interval": 15}
    sg._log_effective_timeframe_once(live_config)
    sg._log_effective_timeframe_once(live_config)  # second call silent

    matching = [m for m in loguru_sink if "signal_generator effective config" in m]
    assert len(matching) == 1, f"expected exactly one drift log, got {len(matching)}"
    message = matching[0]
    assert "timeframe=1m" in message
    assert "scan_interval=15" in message
    assert "drift=True" in message


def test_generate_signals_drift_flag_false_when_defaults_match(loguru_sink):
    import pearlalgo.trading_bots.signal_generator as sg

    sg._LOGGED_EFFECTIVE_TIMEFRAME = False

    match_config = {
        "timeframe": sg.CONFIG["timeframe"],
        "scan_interval": sg.CONFIG["scan_interval"],
    }
    sg._log_effective_timeframe_once(match_config)

    matching = [m for m in loguru_sink if "signal_generator effective config" in m]
    assert len(matching) == 1
    assert "drift=False" in matching[0]


def test_generate_signals_drift_log_handles_missing_keys(loguru_sink):
    """Config without timeframe/scan_interval should not crash."""
    import pearlalgo.trading_bots.signal_generator as sg

    sg._LOGGED_EFFECTIVE_TIMEFRAME = False

    sg._log_effective_timeframe_once({})  # fully empty dict

    matching = [m for m in loguru_sink if "signal_generator effective config" in m]
    assert len(matching) == 1
    assert "timeframe=None" in matching[0]
