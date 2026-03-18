"""Tests for pearlalgo.utils.config_helpers — pure functions, no mocking."""

from __future__ import annotations

import logging

import pytest

from pearlalgo.utils.config_helpers import (
    safe_get_float,
    safe_get_int,
    safe_get_bool,
    safe_get_str,
    safe_cast,
)


# ---------------------------------------------------------------------------
# safe_get_float
# ---------------------------------------------------------------------------

class TestSafeGetFloat:
    def test_present(self):
        assert safe_get_float({"k": 3.14}, "k") == pytest.approx(3.14)

    def test_missing_key(self):
        assert safe_get_float({}, "k", 1.0) == 1.0

    def test_none_value(self):
        assert safe_get_float({"k": None}, "k", 2.0) == 2.0

    def test_string_number(self):
        assert safe_get_float({"k": "3.5"}, "k") == pytest.approx(3.5)

    def test_invalid_string(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = safe_get_float({"k": "abc"}, "k", 0.0)
        assert result == 0.0
        assert "Invalid config" in caplog.text

    def test_warn_false(self, caplog):
        with caplog.at_level(logging.WARNING):
            safe_get_float({"k": "abc"}, "k", 0.0, warn=False)
        assert "Invalid config" not in caplog.text

    def test_context_in_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            safe_get_float({"k": "abc"}, "k", 0.0, context="mymod")
        assert "mymod" in caplog.text


# ---------------------------------------------------------------------------
# safe_get_int
# ---------------------------------------------------------------------------

class TestSafeGetInt:
    def test_present(self):
        assert safe_get_int({"k": 42}, "k") == 42

    def test_float_string(self):
        assert safe_get_int({"k": "3.0"}, "k") == 3

    def test_missing_key(self):
        assert safe_get_int({}, "k", 10) == 10

    def test_none_value(self):
        assert safe_get_int({"k": None}, "k", 5) == 5

    def test_invalid(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = safe_get_int({"k": "abc"}, "k", 0)
        assert result == 0

    def test_clamp_lo(self):
        assert safe_get_int({"k": -5}, "k", 0, lo=0) == 0

    def test_clamp_hi(self):
        assert safe_get_int({"k": 100}, "k", 0, hi=50) == 50

    def test_clamp_both(self):
        assert safe_get_int({"k": 200}, "k", 0, lo=10, hi=50) == 50


# ---------------------------------------------------------------------------
# safe_get_bool
# ---------------------------------------------------------------------------

class TestSafeGetBool:
    def test_bool_true(self):
        assert safe_get_bool({"k": True}, "k") is True

    def test_bool_false(self):
        assert safe_get_bool({"k": False}, "k") is False

    def test_string_true(self):
        for val in ("true", "True", "1", "yes", "on"):
            assert safe_get_bool({"k": val}, "k") is True

    def test_string_false(self):
        for val in ("false", "False", "0", "no", "off", ""):
            assert safe_get_bool({"k": val}, "k") is False

    def test_int_truthy(self):
        assert safe_get_bool({"k": 1}, "k") is True

    def test_int_falsy(self):
        assert safe_get_bool({"k": 0}, "k") is False

    def test_none(self):
        assert safe_get_bool({"k": None}, "k") is False

    def test_missing(self):
        assert safe_get_bool({}, "k", default=True) is True

    def test_invalid_string(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = safe_get_bool({"k": "maybe"}, "k", default=False)
        assert result is False
        assert "Invalid config" in caplog.text


# ---------------------------------------------------------------------------
# safe_get_str
# ---------------------------------------------------------------------------

class TestSafeGetStr:
    def test_present(self):
        assert safe_get_str({"k": "hello"}, "k") == "hello"

    def test_missing(self):
        assert safe_get_str({}, "k", "default") == "default"

    def test_none(self):
        assert safe_get_str({"k": None}, "k", "fallback") == "fallback"

    def test_non_string_converted(self):
        assert safe_get_str({"k": 42}, "k") == "42"


# ---------------------------------------------------------------------------
# safe_cast
# ---------------------------------------------------------------------------

class TestSafeCast:
    def test_float_cast(self):
        assert safe_cast("3.14", float) == pytest.approx(3.14)

    def test_int_cast(self):
        assert safe_cast("42", int) == 42

    def test_none_returns_default(self):
        assert safe_cast(None, float, 0.0) == 0.0

    def test_invalid_returns_default(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = safe_cast("abc", float, 0.0)
        assert result == 0.0
        assert "Failed to cast" in caplog.text

    def test_warn_false(self, caplog):
        with caplog.at_level(logging.WARNING):
            safe_cast("abc", float, 0.0, warn=False)
        assert "Failed to cast" not in caplog.text

    def test_label_in_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            safe_cast("abc", float, 0.0, label="price")
        assert "price" in caplog.text
