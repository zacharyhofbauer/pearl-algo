"""Tests for Trade Database."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pearlalgo.learning.trade_database import TradeDatabase, TradeRecord


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = TradeDatabase(db_path)
        yield db


@pytest.fixture
def sample_trade() -> dict:
    """Sample trade data."""
    return {
        "trade_id": "trade_001",
        "signal_id": "sig_001",
        "signal_type": "momentum_long",
        "direction": "long",
        "entry_price": 15000.0,
        "exit_price": 15020.0,
        "pnl": 40.0,
        "is_win": True,
        "entry_time": "2024-01-02T10:30:00+00:00",
        "exit_time": "2024-01-02T11:00:00+00:00",
        "stop_loss": 14990.0,
        "take_profit": 15025.0,
        "exit_reason": "take_profit",
        "hold_duration_minutes": 30.0,
        "regime": "trending_bullish",
        "context_key": "trending_bullish_med_vol_morning_normal",
        "volatility_percentile": 0.5,
        "volume_percentile": 0.6,
        "features": {"rsi": 0.65, "momentum": 0.7},
    }


class TestTradeDatabase:
    """Test TradeDatabase class."""
    
    def test_initialization(self, temp_db):
        """Test database initialization."""
        assert temp_db.db_path.exists()
    
    def test_add_trade(self, temp_db, sample_trade):
        """Test adding a trade."""
        temp_db.add_trade(**sample_trade)
        
        count = temp_db.get_trade_count()
        assert count == 1
    
    def test_add_multiple_trades(self, temp_db, sample_trade):
        """Test adding multiple trades."""
        for i in range(5):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i:03d}"
            trade["pnl"] = 50.0 if i % 2 == 0 else -30.0
            trade["is_win"] = i % 2 == 0
            temp_db.add_trade(**trade)
        
        count = temp_db.get_trade_count()
        assert count == 5
    
    def test_get_trades_no_filter(self, temp_db, sample_trade):
        """Test getting trades without filters."""
        for i in range(3):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            temp_db.add_trade(**trade)
        
        trades = temp_db.get_trades()
        assert len(trades) == 3
    
    def test_get_trades_filter_signal_type(self, temp_db, sample_trade):
        """Test filtering by signal type."""
        # Add different signal types
        for i, st in enumerate(["momentum_long", "momentum_long", "sr_bounce"]):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["signal_type"] = st
            temp_db.add_trade(**trade)
        
        trades = temp_db.get_trades(signal_type="momentum_long")
        assert len(trades) == 2
    
    def test_get_trades_filter_regime(self, temp_db, sample_trade):
        """Test filtering by regime."""
        for i, regime in enumerate(["trending_bullish", "trending_bullish", "ranging"]):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["regime"] = regime
            temp_db.add_trade(**trade)
        
        trades = temp_db.get_trades(regime="ranging")
        assert len(trades) == 1
    
    def test_get_trades_filter_is_win(self, temp_db, sample_trade):
        """Test filtering by outcome."""
        for i in range(4):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["is_win"] = i < 2
            trade["pnl"] = 50.0 if i < 2 else -30.0
            temp_db.add_trade(**trade)
        
        wins = temp_db.get_trades(is_win=True)
        losses = temp_db.get_trades(is_win=False)
        
        assert len(wins) == 2
        assert len(losses) == 2
    
    def test_get_trades_filter_pnl(self, temp_db, sample_trade):
        """Test filtering by P&L range."""
        for i, pnl in enumerate([100, 50, -20, -50]):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["pnl"] = float(pnl)
            trade["is_win"] = pnl > 0
            temp_db.add_trade(**trade)
        
        positive = temp_db.get_trades(min_pnl=0)
        assert len(positive) == 2
        
        big_loss = temp_db.get_trades(max_pnl=-30)
        assert len(big_loss) == 1
    
    def test_get_performance_by_signal_type(self, temp_db, sample_trade):
        """Test performance breakdown by signal type."""
        trades = [
            ("momentum_long", True, 50),
            ("momentum_long", True, 40),
            ("momentum_long", False, -30),
            ("sr_bounce", True, 60),
            ("sr_bounce", False, -25),
        ]
        
        for i, (st, win, pnl) in enumerate(trades):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["signal_type"] = st
            trade["is_win"] = win
            trade["pnl"] = float(pnl)
            temp_db.add_trade(**trade)
        
        perf = temp_db.get_performance_by_signal_type()
        
        assert "momentum_long" in perf
        assert perf["momentum_long"]["count"] == 3
        assert perf["momentum_long"]["wins"] == 2
        assert perf["sr_bounce"]["count"] == 2
    
    def test_get_performance_by_regime(self, temp_db, sample_trade):
        """Test performance breakdown by regime."""
        trades = [
            ("trending_bullish", True, 50),
            ("trending_bullish", True, 40),
            ("ranging", False, -30),
            ("volatile", False, -50),
        ]
        
        for i, (regime, win, pnl) in enumerate(trades):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["regime"] = regime
            trade["is_win"] = win
            trade["pnl"] = float(pnl)
            temp_db.add_trade(**trade)
        
        perf = temp_db.get_performance_by_regime()
        
        assert "trending_bullish" in perf
        assert perf["trending_bullish"]["win_rate"] == 1.0
        assert perf["ranging"]["win_rate"] == 0.0
    
    def test_get_summary(self, temp_db, sample_trade):
        """Test getting database summary."""
        for i in range(10):
            trade = sample_trade.copy()
            trade["trade_id"] = f"trade_{i}"
            trade["is_win"] = i < 6
            trade["pnl"] = 50.0 if i < 6 else -30.0
            temp_db.add_trade(**trade)
        
        summary = temp_db.get_summary()
        
        assert summary["total_trades"] == 10
        assert summary["wins"] == 6
        assert summary["losses"] == 4
        assert summary["win_rate"] == 0.6
    
    def test_add_regime_snapshot(self, temp_db):
        """Test adding regime history."""
        temp_db.add_regime_snapshot(
            regime="trending_bullish",
            confidence=0.85,
            volatility_percentile=0.6,
            trend_strength=0.7,
        )
        
        # Should not raise
        temp_db.add_regime_snapshot(
            regime="volatile",
            confidence=0.9,
        )
    
    def test_trade_with_features(self, temp_db, sample_trade):
        """Test trade with feature storage."""
        features = {
            "rsi_14": 0.65,
            "momentum_short": 0.7,
            "volume_ratio": 1.2,
        }
        
        trade = sample_trade.copy()
        trade["features"] = features
        temp_db.add_trade(**trade)
        
        trades = temp_db.get_trades()
        assert len(trades) == 1
        
        # Features stored as JSON
        record = trades[0]
        assert record.features_json is not None


class TestTradeRecord:
    """Test TradeRecord dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        record = TradeRecord(
            trade_id="trade_001",
            signal_id="sig_001",
            signal_type="momentum_long",
            direction="long",
            entry_price=15000.0,
            exit_price=15020.0,
            stop_loss=14990.0,
            take_profit=15025.0,
            pnl=40.0,
            is_win=True,
            exit_reason="take_profit",
            entry_time="2024-01-02T10:30:00+00:00",
            exit_time="2024-01-02T11:00:00+00:00",
            hold_duration_minutes=30.0,
            regime="trending_bullish",
            context_key="ctx_001",
            volatility_percentile=0.5,
            volume_percentile=0.6,
            features_json='{"rsi": 0.65}',
            created_at="2024-01-02T11:00:00+00:00",
        )
        
        d = record.to_dict()
        
        assert d["trade_id"] == "trade_001"
        assert d["pnl"] == 40.0
        assert d["features"]["rsi"] == 0.65



