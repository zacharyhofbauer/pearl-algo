"""Tests for pearlalgo.utils.optional_imports."""

from __future__ import annotations

from pearlalgo.utils.optional_imports import (
    SKLEARN_AVAILABLE,
    LIGHTGBM_AVAILABLE,
    XGBOOST_AVAILABLE,
    NUMPY_AVAILABLE,
    get_best_classifier,
    get_available_libraries,
)


class TestAvailabilityFlags:
    def test_numpy_available(self):
        # numpy is always installed
        assert NUMPY_AVAILABLE is True

    def test_sklearn_is_bool(self):
        assert isinstance(SKLEARN_AVAILABLE, bool)

    def test_lightgbm_is_bool(self):
        assert isinstance(LIGHTGBM_AVAILABLE, bool)

    def test_xgboost_is_bool(self):
        assert isinstance(XGBOOST_AVAILABLE, bool)


class TestGetBestClassifier:
    def test_returns_tuple(self):
        cls, name = get_best_classifier()
        assert isinstance(name, str)
        assert name in ("xgboost", "lightgbm", "sklearn", "none")

    def test_classifier_or_none(self):
        cls, name = get_best_classifier()
        if name == "none":
            assert cls is None
        else:
            assert cls is not None


class TestGetAvailableLibraries:
    def test_returns_dict(self):
        result = get_available_libraries()
        assert isinstance(result, dict)
        assert "sklearn" in result
        assert "lightgbm" in result
        assert "xgboost" in result
        assert "numpy" in result

    def test_values_are_bool(self):
        for key, val in get_available_libraries().items():
            assert isinstance(val, bool), f"{key} should be bool"
