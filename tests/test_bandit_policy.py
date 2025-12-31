"""
Tests for Adaptive Bandit Policy

Tests:
- Bandit determinism under fixed RNG seed
- Posterior update math + minimum sample gating
- Shadow vs live mode behavior
- Size multiplier calculation
"""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig, BanditDecision
from pearlalgo.learning.policy_state import PolicyState, SignalTypeStats


class TestSignalTypeStats:
    """Tests for SignalTypeStats class."""
    
    def test_initial_state(self):
        """Stats should initialize with prior values."""
        stats = SignalTypeStats(signal_type="test_type")
        
        assert stats.signal_type == "test_type"
        assert stats.alpha == 2.0  # Prior
        assert stats.beta == 2.0   # Prior
        assert stats.wins == 0
        assert stats.losses == 0
        assert stats.sample_count == 0
        assert stats.win_rate == 0.5  # No data = 50%
        assert stats.expected_win_rate == 0.5  # 2/(2+2) = 0.5
    
    def test_record_win_updates_alpha(self):
        """Recording a win should increment alpha."""
        stats = SignalTypeStats(signal_type="test")
        
        stats.record_win(pnl=100.0)
        
        assert stats.wins == 1
        assert stats.alpha == 3.0  # 2.0 + 1
        assert stats.beta == 2.0   # Unchanged
        assert stats.sample_count == 1
        assert stats.total_pnl == 100.0
    
    def test_record_loss_updates_beta(self):
        """Recording a loss should increment beta."""
        stats = SignalTypeStats(signal_type="test")
        
        stats.record_loss(pnl=-50.0)
        
        assert stats.losses == 1
        assert stats.alpha == 2.0   # Unchanged
        assert stats.beta == 3.0    # 2.0 + 1
        assert stats.sample_count == 1
        assert stats.total_pnl == -50.0
    
    def test_win_rate_calculation(self):
        """Win rate should be wins / (wins + losses)."""
        stats = SignalTypeStats(signal_type="test")
        
        stats.record_win()
        stats.record_win()
        stats.record_loss()
        
        assert stats.wins == 2
        assert stats.losses == 1
        assert stats.win_rate == pytest.approx(2/3, rel=0.01)
    
    def test_expected_win_rate_calculation(self):
        """Expected win rate should be alpha / (alpha + beta)."""
        stats = SignalTypeStats(signal_type="test")
        
        # After 2 wins: alpha=4, beta=2 -> expected = 4/6 = 0.667
        stats.record_win()
        stats.record_win()
        
        assert stats.expected_win_rate == pytest.approx(4/6, rel=0.01)
    
    def test_serialization_roundtrip(self):
        """Stats should survive serialization/deserialization."""
        stats = SignalTypeStats(signal_type="test_roundtrip")
        stats.record_win(pnl=100.0)
        stats.record_loss(pnl=-50.0)
        stats.record_signal()
        
        # Serialize
        data = stats.to_dict()
        
        # Deserialize
        restored = SignalTypeStats.from_dict(data)
        
        assert restored.signal_type == stats.signal_type
        assert restored.alpha == stats.alpha
        assert restored.beta == stats.beta
        assert restored.wins == stats.wins
        assert restored.losses == stats.losses
        assert restored.total_pnl == stats.total_pnl


class TestBanditPolicy:
    """Tests for BanditPolicy class."""
    
    @pytest.fixture
    def policy_config(self):
        """Create a test policy configuration."""
        return BanditConfig(
            enabled=True,
            mode="shadow",
            min_samples_per_type=5,
            explore_rate=0.1,
            decision_threshold=0.3,
            prior_alpha=2.0,
            prior_beta=2.0,
        )
    
    @pytest.fixture
    def policy(self, policy_config):
        """Create a policy with temporary state directory."""
        with TemporaryDirectory() as tmpdir:
            yield BanditPolicy(
                config=policy_config,
                state_dir=Path(tmpdir),
            )
    
    def test_determinism_with_seed(self, policy):
        """Policy should be deterministic with fixed seed."""
        policy.set_seed(42)
        
        # Create a signal type with enough samples
        for _ in range(10):
            policy.state.get_or_create_stats("test_type").record_win()
        
        signal = {"type": "test_type"}
        
        # Get multiple decisions
        decisions = []
        for _ in range(5):
            policy.set_seed(42)  # Reset seed
            decision = policy.decide(signal)
            decisions.append(decision.sampled_score)
        
        # All decisions should be identical with same seed
        assert all(d == decisions[0] for d in decisions)
    
    def test_insufficient_samples_always_executes(self, policy):
        """With insufficient samples, policy should always recommend execute."""
        signal = {"type": "new_type"}
        
        # Policy requires min_samples_per_type=5, we have 0
        decision = policy.decide(signal)
        
        assert decision.execute is True
        assert "insufficient_samples" in decision.reason
        assert decision.is_explore is True
    
    def test_explore_rate(self, policy_config):
        """Explore rate should cause random executes."""
        # Create policy with 100% explore rate
        policy_config.explore_rate = 1.0
        policy_config.min_samples_per_type = 0  # Disable sample gating
        
        with TemporaryDirectory() as tmpdir:
            policy = BanditPolicy(config=policy_config, state_dir=Path(tmpdir))
            
            # Even with losing history, should explore
            for _ in range(10):
                policy.state.get_or_create_stats("losing_type").record_loss()
            
            signal = {"type": "losing_type"}
            decision = policy.decide(signal)
            
            assert decision.execute is True
            assert decision.reason == "explore"
            assert decision.is_explore is True
    
    def test_thompson_sampling_skip(self, policy_config):
        """With bad stats, Thompson sampling should recommend skip."""
        policy_config.explore_rate = 0.0  # Disable exploration
        policy_config.min_samples_per_type = 0  # Disable sample gating
        policy_config.decision_threshold = 0.9  # Very high threshold
        
        with TemporaryDirectory() as tmpdir:
            policy = BanditPolicy(config=policy_config, state_dir=Path(tmpdir))
            
            # Create very bad stats: alpha=2, beta=20 -> expected ~0.1
            stats = policy.state.get_or_create_stats("bad_type")
            for _ in range(18):
                stats.record_loss()
            
            signal = {"type": "bad_type"}
            policy.set_seed(42)  # For reproducibility
            decision = policy.decide(signal)
            
            # With expected ~0.1 and threshold 0.9, should skip
            assert decision.execute is False
            assert "thompson_skip" in decision.reason
    
    def test_thompson_sampling_pass(self, policy_config):
        """With good stats, Thompson sampling should recommend execute."""
        policy_config.explore_rate = 0.0  # Disable exploration
        policy_config.min_samples_per_type = 0
        policy_config.decision_threshold = 0.3  # Low threshold
        
        with TemporaryDirectory() as tmpdir:
            policy = BanditPolicy(config=policy_config, state_dir=Path(tmpdir))
            
            # Create good stats: alpha=20, beta=2 -> expected ~0.91
            stats = policy.state.get_or_create_stats("good_type")
            for _ in range(18):
                stats.record_win()
            
            signal = {"type": "good_type"}
            policy.set_seed(42)
            decision = policy.decide(signal)
            
            # With expected ~0.91 and threshold 0.3, should pass
            assert decision.execute is True
            assert "thompson_pass" in decision.reason
    
    def test_size_multiplier_high_win_rate(self, policy):
        """High win rate should give size multiplier > 1."""
        # 90% win rate -> size boost
        expected_win_rate = 0.9
        multiplier = policy._calculate_size_multiplier(expected_win_rate)
        
        assert multiplier > 1.0
        assert multiplier <= policy.config.max_size_multiplier
    
    def test_size_multiplier_low_win_rate(self, policy):
        """Low win rate should give size multiplier < 1."""
        # 20% win rate -> size reduction
        expected_win_rate = 0.2
        multiplier = policy._calculate_size_multiplier(expected_win_rate)
        
        assert multiplier < 1.0
        assert multiplier >= policy.config.min_size_multiplier
    
    def test_size_multiplier_neutral(self, policy):
        """50% win rate should give size multiplier = 1."""
        expected_win_rate = 0.5
        multiplier = policy._calculate_size_multiplier(expected_win_rate)
        
        assert multiplier == 1.0
    
    def test_record_outcome_updates_stats(self, policy):
        """Recording outcomes should update stats correctly."""
        policy.record_outcome(
            signal_id="test_1",
            signal_type="outcome_test",
            is_win=True,
            pnl=150.0,
        )
        
        stats = policy.state.signal_types.get("outcome_test")
        assert stats is not None
        assert stats.wins == 1
        assert stats.total_pnl == 150.0
        
        policy.record_outcome(
            signal_id="test_2",
            signal_type="outcome_test",
            is_win=False,
            pnl=-75.0,
        )
        
        assert stats.losses == 1
        assert stats.total_pnl == 75.0  # 150 - 75
    
    def test_shadow_mode_no_execution_gating(self, policy_config):
        """Shadow mode should not actually gate execution."""
        policy_config.mode = "shadow"
        
        with TemporaryDirectory() as tmpdir:
            policy = BanditPolicy(config=policy_config, state_dir=Path(tmpdir))
            
            signal = {"type": "any_type"}
            decision = policy.decide(signal)
            
            # In shadow mode, decisions are recommendations only
            assert decision.mode == "shadow"
            # The execute field shows what the policy recommends
            # but it shouldn't actually gate in shadow mode
    
    def test_state_persistence(self, policy_config):
        """Policy state should persist across restarts."""
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            
            # Create policy and record some data
            policy1 = BanditPolicy(config=policy_config, state_dir=state_dir)
            policy1.record_outcome("sig1", "persistent_type", True, 100.0)
            policy1.record_outcome("sig2", "persistent_type", False, -50.0)
            policy1.save_state()
            
            # Create new policy instance
            policy2 = BanditPolicy(config=policy_config, state_dir=state_dir)
            
            # Should have loaded the state
            stats = policy2.state.signal_types.get("persistent_type")
            assert stats is not None
            assert stats.wins == 1
            assert stats.losses == 1
            assert stats.total_pnl == 50.0


class TestPolicyState:
    """Tests for PolicyState class."""
    
    def test_get_or_create_stats(self):
        """Should create new stats if not exists."""
        state = PolicyState()
        
        stats = state.get_or_create_stats("new_type")
        
        assert stats.signal_type == "new_type"
        assert "new_type" in state.signal_types
        
        # Getting again should return same instance
        stats2 = state.get_or_create_stats("new_type")
        assert stats is stats2
    
    def test_record_decision(self):
        """Should track decision counts."""
        state = PolicyState()
        
        state.record_decision("type1", True, "test", 0.8)
        state.record_decision("type2", False, "test", 0.2)
        
        assert state.total_decisions == 2
        assert state.total_executes == 1
        assert state.total_skips == 1
        assert state.last_decision_signal_type == "type2"
        assert state.last_decision_execute is False
    
    def test_serialization_roundtrip(self):
        """State should survive serialization."""
        state = PolicyState()
        state.get_or_create_stats("type1").record_win(100.0)
        state.get_or_create_stats("type2").record_loss(50.0)
        state.record_decision("type1", True, "test", 0.7)
        
        # Serialize and deserialize
        data = state.to_dict()
        restored = PolicyState.from_dict(data)
        
        assert len(restored.signal_types) == 2
        assert restored.signal_types["type1"].wins == 1
        assert restored.signal_types["type2"].losses == 1
        assert restored.total_decisions == 1
    
    def test_get_summary(self):
        """Summary should show top performers."""
        state = PolicyState()
        
        # Create some stats
        good = state.get_or_create_stats("good_type")
        for _ in range(8):
            good.record_win()
        for _ in range(2):
            good.record_loss()
        
        bad = state.get_or_create_stats("bad_type")
        for _ in range(2):
            bad.record_win()
        for _ in range(8):
            bad.record_loss()
        
        summary = state.get_summary()
        
        assert summary["signal_types_tracked"] == 2
        assert len(summary["top_performers"]) > 0




