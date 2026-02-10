"""Tests for pearlalgo.utils.config_helpers -- Issue 6."""

import pytest

from pearlalgo.utils.config_helpers import (
    safe_get_float, safe_get_int, safe_get_bool, safe_get_str, safe_cast,
)


class TestSafeGetFloat:
    def test_valid_float(self):
        assert safe_get_float({"k": 3.14}, "k", 0.0) == 3.14

    def test_valid_string(self):
        assert safe_get_float({"k": "2.5"}, "k", 0.0) == 2.5

    def test_missing_key(self):
        assert safe_get_float({}, "k", 9.9) == 9.9

    def test_none_value(self):
        assert safe_get_float({"k": None}, "k", 1.0) == 1.0

    def test_invalid_string(self):
        assert safe_get_float({"k": "abc"}, "k", 0.0) == 0.0

    def test_zero_is_valid(self):
        assert safe_get_float({"k": 0.0}, "k", 1.0) == 0.0

    def test_negative(self):
        assert safe_get_float({"k": -5.5}, "k", 0.0) == -5.5


class TestSafeGetInt:
    def test_valid_int(self):
        assert safe_get_int({"k": 42}, "k", 0) == 42

    def test_float_string(self):
        assert safe_get_int({"k": "3.0"}, "k", 0) == 3

    def test_missing_key(self):
        assert safe_get_int({}, "k", 7) == 7

    def test_invalid_string(self):
        assert safe_get_int({"k": "xyz"}, "k", 1) == 1

    def test_zero_is_valid(self):
        assert safe_get_int({"k": 0}, "k", 5) == 0


class TestSafeGetBool:
    def test_true_bool(self):
        assert safe_get_bool({"k": True}, "k", False) is True

    def test_false_bool(self):
        assert safe_get_bool({"k": False}, "k", True) is False

    def test_string_true(self):
        assert safe_get_bool({"k": "true"}, "k", False) is True

    def test_string_false(self):
        assert safe_get_bool({"k": "false"}, "k", True) is False

    def test_string_yes(self):
        assert safe_get_bool({"k": "yes"}, "k", False) is True

    def test_string_no(self):
        assert safe_get_bool({"k": "no"}, "k", True) is False

    def test_int_1(self):
        assert safe_get_bool({"k": 1}, "k", False) is True

    def test_int_0(self):
        assert safe_get_bool({"k": 0}, "k", True) is False

    def test_missing_key(self):
        assert safe_get_bool({}, "k", True) is True

    def test_none_value(self):
        assert safe_get_bool({"k": None}, "k", False) is False

    def test_invalid_string(self):
        assert safe_get_bool({"k": "maybe"}, "k", False) is False


class TestSafeGetStr:
    def test_valid_string(self):
        assert safe_get_str({"k": "hello"}, "k", "") == "hello"

    def test_int_value(self):
        assert safe_get_str({"k": 42}, "k", "") == "42"

    def test_missing_key(self):
        assert safe_get_str({}, "k", "default") == "default"


class TestSafeCast:
    def test_valid_cast(self):
        assert safe_cast("42", int, 0) == 42

    def test_none_returns_default(self):
        assert safe_cast(None, int, 0) == 0

    def test_invalid_returns_default(self):
        assert safe_cast("abc", int, -1) == -1

    def test_custom_cast(self):
        assert safe_cast("3.14", float, 0.0) == 3.14
