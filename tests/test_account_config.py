"""Tests for account config schema and propagation."""

import pytest

from pearlalgo.config.config_schema import (
    AccountDisplayConfig,
    AccountsConfig,
    AuditConfig,
    FullServiceConfig,
    validate_config,
)


class TestAccountDisplayConfig:
    """Test AccountDisplayConfig Pydantic model."""

    def test_account_display_config_defaults_to_unknown_badge(self):
        cfg = AccountDisplayConfig()
        assert cfg.display_name == "Unknown"
        assert cfg.badge == "UNKNOWN"
        assert cfg.badge_color == "gray"

    def test_custom_values(self):
        cfg = AccountDisplayConfig(
            display_name="Test Account",
            badge="TEST",
            badge_color="green",
            telegram_prefix="TST",
            description="A test account",
        )
        assert cfg.display_name == "Test Account"
        assert cfg.telegram_prefix == "TST"


class TestAccountsConfig:
    """Test AccountsConfig with default account entries."""

    def test_default_ibkr_virtual(self):
        cfg = AccountsConfig()
        assert cfg.ibkr_virtual.display_name == "IBKR Virtual"
        assert cfg.ibkr_virtual.badge == "VIRTUAL"
        assert cfg.ibkr_virtual.badge_color == "blue"
        assert cfg.ibkr_virtual.telegram_prefix == "IBKR-VIR"

    def test_default_tv_paper(self):
        cfg = AccountsConfig()
        assert cfg.tv_paper.display_name == "Tradovate Paper"
        assert cfg.tv_paper.badge == "PAPER"
        assert cfg.tv_paper.badge_color == "purple"
        assert cfg.tv_paper.telegram_prefix == "TV-PAPER"


class TestAuditConfig:
    """Test AuditConfig Pydantic model."""

    def test_audit_config_defaults_to_90_day_retention(self):
        cfg = AuditConfig()
        assert cfg.retention_days == 90
        assert cfg.snapshot_retention_days == 365

    def test_custom_retention(self):
        cfg = AuditConfig(retention_days=30, snapshot_retention_days=180)
        assert cfg.retention_days == 30
        assert cfg.snapshot_retention_days == 180

    def test_minimum_retention(self):
        with pytest.raises(Exception):
            AuditConfig(retention_days=0)


class TestFullServiceConfigAccounts:
    """Test accounts field in FullServiceConfig."""

    def test_accounts_present_in_full_config(self):
        cfg = FullServiceConfig()
        assert hasattr(cfg, "accounts")
        assert cfg.accounts.ibkr_virtual.display_name == "IBKR Virtual"

    def test_audit_present_in_full_config(self):
        cfg = FullServiceConfig()
        assert hasattr(cfg, "audit")
        assert cfg.audit.retention_days == 90

    def test_validate_config_with_accounts(self):
        config_dict = {
            "accounts": {
                "ibkr_virtual": {"display_name": "My Virtual"},
                "tv_paper": {"display_name": "My Paper"},
            },
            "audit": {"retention_days": 60},
        }
        cfg = validate_config(config_dict)
        assert cfg.accounts.ibkr_virtual.display_name == "My Virtual"
        assert cfg.audit.retention_days == 60

    def test_validate_config_without_accounts(self):
        """Config without accounts section should use defaults."""
        cfg = validate_config({})
        assert cfg.accounts.ibkr_virtual.display_name == "IBKR Virtual"
        assert cfg.accounts.tv_paper.display_name == "Tradovate Paper"
