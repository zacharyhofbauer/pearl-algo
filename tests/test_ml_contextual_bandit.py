"""Tests for Contextual Bandit Policy."""

import tempfile
from pathlib import Path

import pytest

from pearlalgo.learning.contextual_bandit import (
    ContextualBanditPolicy,
    ContextualBanditConfig,
    ContextualDecision,
    ContextFeatures,
    ContextualArmStats,
    ContextualBanditState,
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_context() -> ContextFeatures:
    """Create sample context features."""
    return ContextFeatures(
        regime="trending_bullish",
        volatility_percentile=0.6,
        hour_of_day=10,
        minutes_since_session_open=90,
        is_first_hour=False,
        is_last_hour=False,
        recent_win_rate=0.6,
        recent_streak=2,
        volume_percentile=0.7,
        trend_strength=0.8,
    )


@pytest.fixture
def sample_signal() -> dict:
    """Create sample signal."""
    return {
        "type": "momentum_long",
        "symbol": "MNQ",
        "entry_price": 15000,
        "stop_loss": 14990,
        "take_profit": 15020,
    }


class TestContextFeatures:
    """Test ContextFeatures dataclass."""
    
    def test_to_context_key(self, sample_context):
        """Test context key generation."""
        key = sample_context.to_context_key()
        
        assert "trending_bullish" in key
        assert "med_vol" in key  # 0.6 is medium
        assert "morning" in key  # 10am
    
    def test_to_context_key_different_values(self):
        """Test context key with different values."""
        ctx = ContextFeatures(
            regime="volatile",
            volatility_percentile=0.9,  # High
            hour_of_day=15,  # Afternoon
            is_last_hour=True,
            recent_win_rate=0.8,  # Hot
        )
        
        key = ctx.to_context_key()
        assert "volatile" in key
        assert "high_vol" in key
        assert "close" in key  # last hour
        assert "hot" in key
    
    def test_to_vector(self, sample_context):
        """Test vector conversion."""
        import numpy as np
        
        vector = sample_context.to_vector()
        
        # Should have fixed length
        assert len(vector) > 10
        # Should be numeric (numpy types are numeric)
        assert np.issubdtype(vector.dtype, np.number)
    
    def test_to_dict(self, sample_context):
        """Test dictionary conversion."""
        d = sample_context.to_dict()
        
        assert d["regime"] == "trending_bullish"
        assert d["volatility_percentile"] == 0.6
        assert "context_key" in d
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "regime": "ranging",
            "volatility_percentile": 0.3,
            "hour_of_day": 14,
        }
        
        ctx = ContextFeatures.from_dict(data)
        assert ctx.regime == "ranging"
        assert ctx.volatility_percentile == 0.3
        assert ctx.hour_of_day == 14


class TestContextualArmStats:
    """Test ContextualArmStats class."""
    
    def test_initial_values(self):
        """Test initial statistics."""
        stats = ContextualArmStats(
            signal_type="momentum_long",
            context_key="test",
        )
        
        assert stats.alpha == 2.0  # Prior
        assert stats.beta == 2.0   # Prior
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.sample_count == 0
    
    def test_record_win(self):
        """Test recording a win."""
        stats = ContextualArmStats(signal_type="test", context_key="test")
        stats.record_outcome(is_win=True, pnl=50.0)
        
        assert stats.wins == 1
        assert stats.alpha == 3.0  # Prior + 1
        assert stats.total_pnl == 50.0
    
    def test_record_loss(self):
        """Test recording a loss."""
        stats = ContextualArmStats(signal_type="test", context_key="test")
        stats.record_outcome(is_win=False, pnl=-30.0)
        
        assert stats.losses == 1
        assert stats.beta == 3.0  # Prior + 1
        assert stats.total_pnl == -30.0
    
    def test_win_rate(self):
        """Test win rate calculation."""
        stats = ContextualArmStats(signal_type="test", context_key="test")
        
        # 3 wins, 2 losses
        for _ in range(3):
            stats.record_outcome(True)
        for _ in range(2):
            stats.record_outcome(False)
        
        assert stats.win_rate == pytest.approx(0.6)
    
    def test_expected_win_rate(self):
        """Test expected win rate from Beta distribution."""
        stats = ContextualArmStats(signal_type="test", context_key="test")
        
        # With prior (2, 2), expected = 0.5
        assert stats.expected_win_rate == pytest.approx(0.5)
        
        # Add some wins
        for _ in range(6):
            stats.record_outcome(True)
        
        # Now expected = 8 / 10 = 0.8
        assert stats.expected_win_rate == pytest.approx(0.8)
    
    def test_sample(self):
        """Test sampling from Beta distribution."""
        import random
        
        stats = ContextualArmStats(signal_type="test", context_key="test")
        
        rng = random.Random(42)
        samples = [stats.sample(rng) for _ in range(100)]
        
        # Samples should be in [0, 1]
        assert all(0 <= s <= 1 for s in samples)
        
        # Mean should be close to expected
        assert abs(sum(samples) / len(samples) - stats.expected_win_rate) < 0.1


class TestContextualBanditState:
    """Test ContextualBanditState class."""
    
    def test_get_stats_creates_new(self):
        """Test that get_stats creates new stats if not exists."""
        state = ContextualBanditState()
        
        stats = state.get_stats("momentum_long", "trending_high_vol")
        
        assert stats.signal_type == "momentum_long"
        assert stats.context_key == "trending_high_vol"
        assert stats.sample_count == 0
    
    def test_get_stats_returns_existing(self):
        """Test that get_stats returns existing stats."""
        state = ContextualBanditState()
        
        # Create and record
        stats1 = state.get_stats("momentum_long", "ctx1")
        stats1.record_outcome(True, 50)
        
        # Get again
        stats2 = state.get_stats("momentum_long", "ctx1")
        
        assert stats2.wins == 1
    
    def test_record_outcome(self):
        """Test recording outcomes."""
        state = ContextualBanditState()
        
        state.record_outcome("momentum_long", "ctx1", True, 50)
        state.record_outcome("momentum_long", "ctx1", False, -30)
        
        ctx_stats = state.get_stats("momentum_long", "ctx1")
        global_stats = state.get_global_stats("momentum_long")
        
        assert ctx_stats.wins == 1
        assert ctx_stats.losses == 1
        assert global_stats.wins == 1
        assert global_stats.losses == 1
    
    def test_serialization(self, temp_dir):
        """Test save and load."""
        state = ContextualBanditState()
        state.record_outcome("momentum_long", "ctx1", True, 50)
        state.record_outcome("momentum_short", "ctx2", False, -30)
        state.record_decision(True)
        state.record_decision(False)
        
        # Save
        file_path = temp_dir / "state.json"
        state.save(file_path)
        
        # Load
        loaded = ContextualBanditState.load(file_path)
        
        assert loaded.total_decisions == 2
        assert loaded.total_executes == 1
        assert loaded.total_skips == 1
        assert "momentum_long" in loaded.contextual_stats


class TestContextualBanditPolicy:
    """Test ContextualBanditPolicy class."""
    
    def test_initialization(self, temp_dir):
        """Test policy initialization."""
        config = ContextualBanditConfig(
            enabled=True,
            mode="shadow",
            decision_threshold=0.3,
        )
        
        policy = ContextualBanditPolicy(config, state_dir=temp_dir)
        
        assert policy.config.mode == "shadow"
        assert policy.config.decision_threshold == 0.3
    
    def test_decide_explore_new_context(self, temp_dir, sample_signal, sample_context):
        """Test decision for new context (should explore)."""
        policy = ContextualBanditPolicy(
            ContextualBanditConfig(min_samples_per_context=5),
            state_dir=temp_dir,
        )
        
        decision = policy.decide(sample_signal, sample_context)
        
        assert decision.execute is True  # Should explore
        assert "explore" in decision.reason
        assert decision.context_sample_count == 0
    
    def test_decide_with_history(self, temp_dir, sample_signal, sample_context):
        """Test decision with sufficient history."""
        policy = ContextualBanditPolicy(
            ContextualBanditConfig(
                min_samples_per_context=3,
                explore_rate=0.0,  # No random exploration
            ),
            state_dir=temp_dir,
        )
        policy.set_seed(42)
        
        # Add history
        for _ in range(5):
            policy.record_outcome(
                signal_id="test",
                signal_type="momentum_long",
                context=sample_context,
                is_win=True,
                pnl=50,
            )
        
        decision = policy.decide(sample_signal, sample_context)
        
        assert decision.context_sample_count >= 5
        assert "thompson" in decision.reason.lower() or "explore" in decision.reason.lower()
    
    def test_record_outcome(self, temp_dir, sample_context):
        """Test recording trade outcomes."""
        policy = ContextualBanditPolicy(state_dir=temp_dir)
        
        policy.record_outcome(
            signal_id="sig1",
            signal_type="momentum_long",
            context=sample_context,
            is_win=True,
            pnl=50.0,
        )
        
        # Check state updated
        context_key = sample_context.to_context_key()
        stats = policy.state.get_stats("momentum_long", context_key)
        
        assert stats.wins == 1
    
    def test_get_status(self, temp_dir, sample_context):
        """Test getting policy status."""
        policy = ContextualBanditPolicy(state_dir=temp_dir)
        
        # Add some data
        for i in range(3):
            policy.record_outcome(
                signal_id=f"sig{i}",
                signal_type="momentum_long",
                context=sample_context,
                is_win=i % 2 == 0,
            )
        
        status = policy.get_status()
        
        assert "enabled" in status
        assert "mode" in status
        assert "total_decisions" in status
    
    def test_get_best_contexts(self, temp_dir):
        """Test getting best performing contexts."""
        policy = ContextualBanditPolicy(
            ContextualBanditConfig(min_samples_per_context=2),
            state_dir=temp_dir,
        )
        
        # Add data for different contexts
        good_ctx = ContextFeatures(regime="trending_bullish")
        bad_ctx = ContextFeatures(regime="ranging")
        
        # Good context: 4 wins, 1 loss
        for _ in range(4):
            policy.record_outcome("id", "momentum_long", good_ctx, True, 50)
        policy.record_outcome("id", "momentum_long", good_ctx, False, -30)
        
        # Bad context: 1 win, 4 losses
        policy.record_outcome("id", "momentum_long", bad_ctx, True, 50)
        for _ in range(4):
            policy.record_outcome("id", "momentum_long", bad_ctx, False, -30)
        
        best = policy.get_best_contexts("momentum_long", top_n=1)
        worst = policy.get_worst_contexts("momentum_long", top_n=1)
        
        assert len(best) >= 1
        assert len(worst) >= 1
        # Best should have higher win rate than worst
        if best and worst:
            assert "80%" in best[0]["win_rate"] or "trending" in best[0]["context_key"]

