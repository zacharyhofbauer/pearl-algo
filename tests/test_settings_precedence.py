"""
Settings Precedence and Validation Tests

Tests:
- Environment variable precedence: IBKR_* > PEARLALGO_IB_* > defaults
- Port validation (1-65535)
- Client ID validation (0-100)
- Invalid value handling
"""

import pytest
from unittest.mock import patch


class TestSettingsPrecedence:
    """Test environment variable precedence rules.
    
    These tests mock os.getenv to test the precedence logic in Settings.__init__
    without interference from load_dotenv().
    """

    def test_defaults_used_when_no_env_vars(self):
        """Test that defaults are used when no environment variables are set."""
        # Mock os.getenv to return None for all IBKR/PEARLALGO vars
        def mock_getenv(key, default=None):
            # Return None for all our vars to test defaults
            if key.startswith("IBKR_") or key.startswith("PEARLALGO_"):
                return None
            return default
        
        with patch("os.getenv", side_effect=mock_getenv):
            from pearlalgo.config.settings import Settings
            settings = Settings()
            
            assert settings.ib_host == "127.0.0.1"
            assert settings.ib_port == 4002
            assert settings.ib_client_id == 1
            assert settings.ib_data_client_id is None

    def test_pearlalgo_env_vars_override_defaults(self):
        """Test that PEARLALGO_IB_* env vars override defaults."""
        env_mapping = {
            "PEARLALGO_IB_HOST": "192.168.1.100",
            "PEARLALGO_IB_PORT": "7497",
            "PEARLALGO_IB_CLIENT_ID": "10",
            "PEARLALGO_IB_DATA_CLIENT_ID": "20",
        }
        
        def mock_getenv(key, default=None):
            return env_mapping.get(key, None)
        
        with patch("os.getenv", side_effect=mock_getenv):
            from pearlalgo.config.settings import Settings
            settings = Settings()
            
            assert settings.ib_host == "192.168.1.100"
            assert settings.ib_port == 7497
            assert settings.ib_client_id == 10
            assert settings.ib_data_client_id == 20

    def test_ibkr_env_vars_take_highest_precedence(self):
        """Test that IBKR_* env vars override PEARLALGO_IB_* vars."""
        env_mapping = {
            # IBKR_* should win
            "IBKR_HOST": "10.0.0.1",
            "IBKR_PORT": "4001",
            "IBKR_CLIENT_ID": "5",
            "IBKR_DATA_CLIENT_ID": "6",
            # These should be ignored
            "PEARLALGO_IB_HOST": "192.168.1.100",
            "PEARLALGO_IB_PORT": "7497",
            "PEARLALGO_IB_CLIENT_ID": "10",
            "PEARLALGO_IB_DATA_CLIENT_ID": "20",
        }
        
        def mock_getenv(key, default=None):
            return env_mapping.get(key, None)
        
        with patch("os.getenv", side_effect=mock_getenv):
            from pearlalgo.config.settings import Settings
            settings = Settings()
            
            # IBKR_* should win
            assert settings.ib_host == "10.0.0.1"
            assert settings.ib_port == 4001
            assert settings.ib_client_id == 5
            assert settings.ib_data_client_id == 6

    def test_partial_override_ibkr_over_pearlalgo(self):
        """Test partial override: some IBKR_*, some PEARLALGO_*."""
        env_mapping = {
            "IBKR_HOST": "10.0.0.1",  # Should win
            "PEARLALGO_IB_PORT": "7497",  # Should be used (no IBKR_PORT)
            "IBKR_CLIENT_ID": "5",  # Should win
            "PEARLALGO_IB_DATA_CLIENT_ID": "20",  # Should be used (no IBKR_DATA_CLIENT_ID)
        }
        
        def mock_getenv(key, default=None):
            return env_mapping.get(key, None)
        
        with patch("os.getenv", side_effect=mock_getenv):
            from pearlalgo.config.settings import Settings
            settings = Settings()
            
            assert settings.ib_host == "10.0.0.1"  # From IBKR_HOST
            assert settings.ib_port == 7497  # From PEARLALGO_IB_PORT
            assert settings.ib_client_id == 5  # From IBKR_CLIENT_ID
            assert settings.ib_data_client_id == 20  # From PEARLALGO_IB_DATA_CLIENT_ID

    def test_constructor_args_override_env_vars(self):
        """Test that explicit constructor arguments override environment variables."""
        from pearlalgo.config.settings import Settings
        
        # Regardless of env vars, constructor args should take precedence
        settings = Settings(
            ib_host="explicit-host",
            ib_port=9999,
            ib_client_id=42,
            ib_data_client_id=43,
        )
        
        assert settings.ib_host == "explicit-host"
        assert settings.ib_port == 9999
        assert settings.ib_client_id == 42
        assert settings.ib_data_client_id == 43

    def test_empty_string_env_vars_use_defaults(self):
        """Test that empty string env vars fall back to defaults."""
        env_mapping = {
            "IBKR_HOST": "",
            "PEARLALGO_IB_HOST": "",
        }
        
        def mock_getenv(key, default=None):
            return env_mapping.get(key, None)
        
        with patch("os.getenv", side_effect=mock_getenv):
            from pearlalgo.config.settings import Settings
            settings = Settings()
            
            # Empty strings are falsy, so should use default
            assert settings.ib_host == "127.0.0.1"


class TestSettingsValidation:
    """Test settings validation rules."""

    def test_valid_port_range(self):
        """Test that valid ports (1-65535) are accepted."""
        from pearlalgo.config.settings import Settings
        
        # Test boundaries
        valid_ports = [1, 4002, 7497, 65535]
        for port in valid_ports:
            settings = Settings(ib_port=port)
            assert settings.ib_port == port

    def test_invalid_port_zero(self):
        """Test that port 0 is rejected."""
        from pearlalgo.config.settings import Settings
        
        with pytest.raises(ValueError, match="IBKR port must be between 1 and 65535"):
            Settings(ib_port=0)

    def test_invalid_port_negative(self):
        """Test that negative ports are rejected."""
        from pearlalgo.config.settings import Settings
        
        with pytest.raises(ValueError, match="IBKR port must be between 1 and 65535"):
            Settings(ib_port=-1)

    def test_invalid_port_too_high(self):
        """Test that ports > 65535 are rejected."""
        from pearlalgo.config.settings import Settings
        
        with pytest.raises(ValueError, match="IBKR port must be between 1 and 65535"):
            Settings(ib_port=65536)

    def test_valid_client_id_range(self):
        """Test that valid client IDs (0-100) are accepted."""
        from pearlalgo.config.settings import Settings
        
        valid_client_ids = [0, 1, 50, 100]
        for client_id in valid_client_ids:
            settings = Settings(ib_client_id=client_id)
            assert settings.ib_client_id == client_id

    def test_invalid_client_id_negative(self):
        """Test that negative client IDs are rejected."""
        from pearlalgo.config.settings import Settings
        
        with pytest.raises(ValueError, match="IBKR client ID must be between 0 and 100"):
            Settings(ib_client_id=-1)

    def test_invalid_client_id_too_high(self):
        """Test that client IDs > 100 are rejected."""
        from pearlalgo.config.settings import Settings
        
        with pytest.raises(ValueError, match="IBKR client ID must be between 0 and 100"):
            Settings(ib_client_id=101)

    def test_data_client_id_none_allowed(self):
        """Test that data_client_id can be None."""
        from pearlalgo.config.settings import Settings
        
        settings = Settings(ib_data_client_id=None)
        assert settings.ib_data_client_id is None

    def test_data_client_id_validation(self):
        """Test that data_client_id validation works same as client_id."""
        from pearlalgo.config.settings import Settings
        
        # Valid
        settings = Settings(ib_data_client_id=50)
        assert settings.ib_data_client_id == 50
        
        # Invalid
        with pytest.raises(ValueError, match="IBKR client ID must be between 0 and 100"):
            Settings(ib_data_client_id=200)


class TestRequireKeys:
    """Test the require_keys helper function."""

    def test_require_keys_pass(self):
        """Test that require_keys passes when all keys are present."""
        from pearlalgo.config.settings import Settings, require_keys
        
        settings = Settings(ib_host="127.0.0.1", ib_port=4002)
        # Should not raise
        require_keys(settings, ["ib_host", "ib_port"])

    def test_require_keys_fail_missing(self):
        """Test that require_keys fails when keys are missing/falsey."""
        from pearlalgo.config.settings import Settings, require_keys
        
        # Create settings with ib_data_client_id explicitly None
        settings = Settings(ib_data_client_id=None)
        # ib_data_client_id is None, should fail
        with pytest.raises(RuntimeError, match="Missing required settings"):
            require_keys(settings, ["ib_data_client_id"])

    def test_require_keys_fail_empty_string(self):
        """Test that require_keys fails for empty string values."""
        from pearlalgo.config.settings import Settings, require_keys
        
        settings = Settings(ib_host="")
        with pytest.raises(RuntimeError, match="Missing required settings"):
            require_keys(settings, ["ib_host"])


class TestGetSettings:
    """Test the get_settings helper function."""

    def test_get_settings_returns_settings_instance(self):
        """Test that get_settings returns a Settings instance."""
        from pearlalgo.config.settings import get_settings, Settings
        
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_ignores_profile_and_config_file(self):
        """Test that profile and config_file params are ignored (backwards compat)."""
        from pearlalgo.config.settings import get_settings, Settings
        
        # Should not raise even with arbitrary values
        settings = get_settings(profile="production", config_file="/nonexistent/path.yaml")
        assert isinstance(settings, Settings)
