"""
Tests for TvPaperChallengeState dataclass and parser.

Covers:
- Parsing with all fields present
- Parsing with missing fields (verify defaults)
- Parsing with malformed data (bad types, None values)
- Parsing with empty dict
- Parsing with legacy "mffu" key (should NOT work — clean break)
- to_dict round-trip
"""

from __future__ import annotations

import pytest

from pearlalgo.api.data_layer import TvPaperChallengeState


# ---------------------------------------------------------------------------
# Happy path: all fields present
# ---------------------------------------------------------------------------

class TestFromChallengeDataAllFields:

    def test_parses_all_fields(self):
        data = {
            "tv_paper": {
                "stage": "sim_funded",
                "eod_high_water_mark": 51500.0,
                "current_drawdown_floor": 49500.0,
                "drawdown_locked": True,
                "consistency": {"met": True, "best_day_pct": 30.0},
                "min_days": {"days_traded": 5, "days_required": 2, "met": True},
                "trading_days_count": 5,
                "max_contracts_mini": 3,
            }
        }
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.stage == "sim_funded"
        assert state.eod_high_water_mark == 51500.0
        assert state.current_drawdown_floor == 49500.0
        assert state.drawdown_locked is True
        assert state.consistency == {"met": True, "best_day_pct": 30.0}
        assert state.min_days == {"days_traded": 5, "days_required": 2, "met": True}
        assert state.trading_days_count == 5
        assert state.max_contracts_mini == 3


# ---------------------------------------------------------------------------
# Missing fields: verify defaults
# ---------------------------------------------------------------------------

class TestFromChallengeDataDefaults:

    def test_empty_tv_paper_dict_uses_defaults(self):
        data = {"tv_paper": {}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.stage == "evaluation"
        assert state.eod_high_water_mark is None
        assert state.current_drawdown_floor is None
        assert state.drawdown_locked is False
        assert state.consistency == {}
        assert state.min_days == {}
        assert state.trading_days_count == 0
        assert state.max_contracts_mini == 5

    def test_partial_fields(self):
        data = {"tv_paper": {"stage": "live", "drawdown_locked": True}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.stage == "live"
        assert state.drawdown_locked is True
        assert state.eod_high_water_mark is None
        assert state.trading_days_count == 0


# ---------------------------------------------------------------------------
# Malformed data: bad types, None values
# ---------------------------------------------------------------------------

class TestFromChallengeDataMalformed:

    def test_consistency_is_not_dict_uses_default(self):
        data = {"tv_paper": {"consistency": "invalid"}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.consistency == {}

    def test_min_days_is_not_dict_uses_default(self):
        data = {"tv_paper": {"min_days": 42}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.min_days == {}

    def test_eod_hwm_non_numeric_returns_none(self):
        data = {"tv_paper": {"eod_high_water_mark": "not-a-number"}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.eod_high_water_mark is None

    def test_drawdown_floor_none_returns_none(self):
        data = {"tv_paper": {"current_drawdown_floor": None}}
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        assert state.current_drawdown_floor is None


# ---------------------------------------------------------------------------
# Empty / missing tv_paper key
# ---------------------------------------------------------------------------

class TestFromChallengeDataMissing:

    def test_empty_dict_returns_none(self):
        assert TvPaperChallengeState.from_challenge_data({}) is None

    def test_no_tv_paper_key_returns_none(self):
        data = {"config": {"enabled": True}}
        assert TvPaperChallengeState.from_challenge_data(data) is None

    def test_tv_paper_is_none_returns_none(self):
        data = {"tv_paper": None}
        assert TvPaperChallengeState.from_challenge_data(data) is None

    def test_tv_paper_is_string_returns_none(self):
        data = {"tv_paper": "invalid"}
        assert TvPaperChallengeState.from_challenge_data(data) is None


# ---------------------------------------------------------------------------
# Legacy "mffu" key should NOT work (clean break)
# ---------------------------------------------------------------------------

class TestLegacyMffuKey:

    def test_mffu_key_not_parsed(self):
        data = {"mffu": {"stage": "evaluation", "drawdown_locked": True}}
        assert TvPaperChallengeState.from_challenge_data(data) is None


# ---------------------------------------------------------------------------
# to_dict round-trip
# ---------------------------------------------------------------------------

class TestToDict:

    def test_round_trip(self):
        data = {
            "tv_paper": {
                "stage": "evaluation",
                "eod_high_water_mark": 50500.0,
                "current_drawdown_floor": 48000.0,
                "drawdown_locked": False,
                "consistency": {"met": False, "best_day_pct": 55.0},
                "min_days": {"days_traded": 1, "days_required": 2, "met": False},
                "trading_days_count": 1,
                "max_contracts_mini": 5,
            }
        }
        state = TvPaperChallengeState.from_challenge_data(data)
        assert state is not None
        d = state.to_dict()
        assert d["stage"] == "evaluation"
        assert d["eod_high_water_mark"] == 50500.0
        assert d["current_drawdown_floor"] == 48000.0
        assert d["drawdown_locked"] is False
        assert d["consistency"] == {"met": False, "best_day_pct": 55.0}
        assert d["trading_days_count"] == 1
        assert d["max_contracts_mini"] == 5

    def test_defaults_to_dict(self):
        state = TvPaperChallengeState()
        d = state.to_dict()
        assert d["stage"] == "evaluation"
        assert d["eod_high_water_mark"] is None
        assert d["current_drawdown_floor"] is None
        assert d["drawdown_locked"] is False
