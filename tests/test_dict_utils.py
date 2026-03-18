"""Tests for pearlalgo.utils.dict_utils — pure functions, no mocking."""

from __future__ import annotations

from pearlalgo.utils.dict_utils import deep_merge, deep_merge_inplace


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 20, "c": 3}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 20, "c": 3}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 20, "z": 30}, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3, "c": 4}

    def test_does_not_mutate_inputs(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        deep_merge(base, override)
        assert base == {"a": {"x": 1}}
        assert override == {"a": {"y": 2}}

    def test_empty_override(self):
        base = {"a": 1}
        assert deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        assert deep_merge({}, {"a": 1}) == {"a": 1}

    def test_override_dict_with_scalar(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        result = deep_merge(base, override)
        assert result == {"a": "flat"}


class TestDeepMergeInplace:
    def test_mutates_dst(self):
        dst = {"a": {"x": 1}}
        src = {"a": {"y": 2}}
        deep_merge_inplace(dst, src)
        assert dst == {"a": {"x": 1, "y": 2}}

    def test_adds_new_keys(self):
        dst = {"a": 1}
        deep_merge_inplace(dst, {"b": 2})
        assert dst == {"a": 1, "b": 2}

    def test_returns_dst(self):
        dst = {"a": 1}
        result = deep_merge_inplace(dst, {"b": 2})
        assert result is dst

    def test_override_scalar_with_dict(self):
        dst = {"a": "flat"}
        deep_merge_inplace(dst, {"a": {"nested": True}})
        assert dst == {"a": {"nested": True}}
