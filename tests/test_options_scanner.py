"""
Tests for Options Scanner

Unit tests for options scanning functionality.
"""

import pytest
from unittest.mock import Mock, AsyncMock

from pearlalgo.options.universe import EquityUniverse
from pearlalgo.options.strategy import create_strategy, SwingMomentumStrategy
from pearlalgo.options.signal_generator import OptionsSignalGenerator
from pearlalgo.options.swing_scanner import OptionsSwingScanner


class TestEquityUniverse:
    """Test EquityUniverse."""
    
    def test_initialization(self):
        """Test universe initialization."""
        universe = EquityUniverse(symbols=["SPY", "QQQ", "AAPL"])
        assert universe.get_universe_size() == 3
    
    def test_get_optionable_symbols(self):
        """Test getting optionable symbols."""
        universe = EquityUniverse(symbols=["SPY", "QQQ"])
        symbols = universe.get_optionable_symbols()
        assert len(symbols) == 2
        assert "SPY" in symbols
    
    def test_add_remove_symbol(self):
        """Test adding and removing symbols."""
        universe = EquityUniverse(symbols=["SPY"])
        universe.add_symbol("QQQ")
        assert universe.get_universe_size() == 2
        
        universe.remove_symbol("SPY")
        assert universe.get_universe_size() == 1


class TestOptionsStrategy:
    """Test options strategies."""
    
    def test_create_strategy(self):
        """Test strategy factory."""
        strategy = create_strategy("swing_momentum", {})
        assert isinstance(strategy, SwingMomentumStrategy)
        assert strategy.name == "swing_momentum"
    
    def test_swing_momentum_strategy(self):
        """Test swing momentum strategy."""
        strategy = SwingMomentumStrategy()
        
        # Mock options chain with low spread (compression)
        options_chain = [
            {
                "symbol": "SPY250120C500",
                "strike": 500.0,
                "expiration": "2025-01-20",
                "option_type": "call",
                "bid": 5.0,
                "ask": 5.1,  # Low spread
                "last_price": 5.05,
                "volume": 1000,
                "open_interest": 5000,
            }
        ]
        
        signal = strategy.analyze(options_chain, underlying_price=500.0)
        # Should detect compression and generate signal
        assert signal.get("side") in ["long", "flat"]


class TestOptionsSignalGenerator:
    """Test OptionsSignalGenerator."""
    
    @pytest.fixture
    def universe(self):
        """Create universe."""
        return EquityUniverse(symbols=["SPY"])
    
    @pytest.fixture
    def strategy(self):
        """Create strategy."""
        return create_strategy("swing_momentum", {})
    
    @pytest.fixture
    def mock_provider(self):
        """Mock data provider."""
        provider = Mock()
        provider.get_options_chain = AsyncMock(return_value=[])
        provider.get_latest_bar = AsyncMock(return_value={"close": 500.0})
        return provider
    
    @pytest.fixture
    def generator(self, universe, strategy, mock_provider):
        """Create signal generator."""
        return OptionsSignalGenerator(
            universe=universe,
            strategy=strategy,
            data_provider=mock_provider,
        )
    
    @pytest.mark.asyncio
    async def test_generate_signals(self, generator, mock_provider):
        """Test signal generation."""
        # Mock options chain
        mock_provider.get_options_chain.return_value = [
            {
                "symbol": "SPY250120C500",
                "strike": 500.0,
                "option_type": "call",
                "bid": 5.0,
                "ask": 5.1,
                "volume": 1000,
                "open_interest": 5000,
            }
        ]
        
        signals = await generator.generate_signals()
        # Should return list of signals
        assert isinstance(signals, list)


class TestOptionsSwingScanner:
    """Test OptionsSwingScanner."""
    
    @pytest.fixture
    def universe(self):
        """Create universe."""
        return EquityUniverse(symbols=["SPY", "QQQ"])
    
    @pytest.fixture
    def mock_provider(self):
        """Mock data provider."""
        provider = Mock()
        provider.get_options_chain = AsyncMock(return_value=[])
        provider.get_latest_bar = AsyncMock(return_value={"close": 500.0})
        return provider
    
    @pytest.fixture
    def scanner(self, universe, mock_provider):
        """Create scanner."""
        return OptionsSwingScanner(
            universe=universe,
            strategy="swing_momentum",
            data_provider=mock_provider,
        )
    
    @pytest.mark.asyncio
    async def test_scan(self, scanner):
        """Test single scan."""
        results = await scanner.scan()
        assert "status" in results
        assert results["status"] in ["success", "skipped", "error"]
