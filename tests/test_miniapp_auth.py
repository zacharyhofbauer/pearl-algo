"""
Unit tests for Mini App authentication.

Tests:
- initData validation (signature, expiration, parsing)
- Access control (me-only mode)
- Error handling
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from pearlalgo.miniapp.auth import (
    AuthError,
    InitData,
    InitDataValidator,
    TelegramUser,
)


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

# Test bot token (not a real token)
TEST_BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
TEST_USER_ID = 123456789
TEST_ALLOWED_USER_ID = 123456789


def _compute_secret_key(bot_token: str) -> bytes:
    """Compute the secret key from bot token."""
    return hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256
    ).digest()


def _create_init_data(
    user_id: int = TEST_USER_ID,
    auth_date: int = None,
    bot_token: str = TEST_BOT_TOKEN,
    extra_fields: dict = None,
) -> str:
    """
    Create a valid initData string for testing.
    
    Args:
        user_id: User ID to include
        auth_date: Unix timestamp (defaults to now)
        bot_token: Bot token for signing
        extra_fields: Additional fields to include
        
    Returns:
        URL-encoded initData string with valid signature
    """
    if auth_date is None:
        auth_date = int(time.time())
    
    # Build user JSON
    user = {
        "id": user_id,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
    }
    
    # Build data dict
    data = {
        "user": json.dumps(user),
        "auth_date": str(auth_date),
    }
    
    if extra_fields:
        data.update(extra_fields)
    
    # Build data-check-string (sorted keys, newline separated)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    
    # Compute hash
    secret_key = _compute_secret_key(bot_token)
    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Add hash to data
    data["hash"] = computed_hash
    
    # URL encode
    return urlencode(data)


# ---------------------------------------------------------------------------
# Tests: InitDataValidator
# ---------------------------------------------------------------------------

class TestInitDataValidator:
    """Tests for InitDataValidator."""
    
    def test_valid_init_data(self):
        """Test validation of correctly signed initData."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,  # Don't restrict
        )
        
        init_data_raw = _create_init_data()
        result = validator.validate(init_data_raw)
        
        assert isinstance(result, InitData)
        assert result.user is not None
        assert result.user.id == TEST_USER_ID
        assert result.user.first_name == "Test"
    
    def test_invalid_signature(self):
        """Test rejection of initData with invalid signature."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
        )
        
        # Create valid initData then tamper with it
        init_data_raw = _create_init_data()
        # Replace hash with invalid one
        tampered = init_data_raw.replace("hash=", "hash=invalid")
        
        with pytest.raises(AuthError, match="Invalid initData signature"):
            validator.validate(tampered)
    
    def test_missing_hash(self):
        """Test rejection of initData without hash."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
        )
        
        # Create initData without hash
        init_data_raw = "user=%7B%22id%22%3A123%7D&auth_date=1234567890"
        
        with pytest.raises(AuthError, match="Missing hash"):
            validator.validate(init_data_raw)
    
    def test_empty_init_data(self):
        """Test rejection of empty initData."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
        )
        
        with pytest.raises(AuthError, match="Empty initData"):
            validator.validate("")
    
    def test_expired_init_data(self):
        """Test rejection of expired initData."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
            max_age_seconds=3600,  # 1 hour
        )
        
        # Create initData from 2 hours ago
        old_auth_date = int(time.time()) - 7200
        init_data_raw = _create_init_data(auth_date=old_auth_date)
        
        with pytest.raises(AuthError, match="initData expired"):
            validator.validate(init_data_raw)
    
    def test_future_init_data(self):
        """Test rejection of initData from the future."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
        )
        
        # Create initData from 10 minutes in the future
        future_auth_date = int(time.time()) + 600
        init_data_raw = _create_init_data(auth_date=future_auth_date)
        
        with pytest.raises(AuthError, match="initData from the future"):
            validator.validate(init_data_raw)
    
    def test_me_only_mode_authorized(self):
        """Test me-only mode with authorized user."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=TEST_USER_ID,
        )
        
        init_data_raw = _create_init_data(user_id=TEST_USER_ID)
        result = validator.validate(init_data_raw)
        
        assert result.user.id == TEST_USER_ID
    
    def test_me_only_mode_unauthorized(self):
        """Test me-only mode with unauthorized user."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=TEST_USER_ID,
        )
        
        # Create initData with different user ID
        init_data_raw = _create_init_data(user_id=987654321)
        
        with pytest.raises(AuthError, match="not authorized"):
            validator.validate(init_data_raw)
    
    def test_wrong_bot_token(self):
        """Test rejection when validator uses wrong bot token."""
        validator = InitDataValidator(
            bot_token="wrong:token",
            allowed_user_id=None,
        )
        
        # Create initData with correct token
        init_data_raw = _create_init_data(bot_token=TEST_BOT_TOKEN)
        
        with pytest.raises(AuthError, match="Invalid initData signature"):
            validator.validate(init_data_raw)
    
    def test_init_data_with_extra_fields(self):
        """Test validation with additional fields."""
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
        )
        
        init_data_raw = _create_init_data(
            extra_fields={
                "chat_instance": "12345",
                "chat_type": "private",
                "query_id": "abc123",
            }
        )
        result = validator.validate(init_data_raw)
        
        assert result.chat_instance == "12345"
        assert result.chat_type == "private"
        assert result.query_id == "abc123"
    
    def test_valid_auth_date_boundary(self):
        """Test auth_date at boundary of max age."""
        max_age = 3600
        validator = InitDataValidator(
            bot_token=TEST_BOT_TOKEN,
            allowed_user_id=None,
            max_age_seconds=max_age,
        )
        
        # Create initData just under max age (should pass)
        just_under = int(time.time()) - (max_age - 60)
        init_data_raw = _create_init_data(auth_date=just_under)
        result = validator.validate(init_data_raw)
        assert result is not None
        
        # Create initData just over max age (should fail)
        just_over = int(time.time()) - (max_age + 60)
        init_data_raw_expired = _create_init_data(auth_date=just_over)
        with pytest.raises(AuthError, match="initData expired"):
            validator.validate(init_data_raw_expired)


# ---------------------------------------------------------------------------
# Tests: TelegramUser
# ---------------------------------------------------------------------------

class TestTelegramUser:
    """Tests for TelegramUser model."""
    
    def test_minimal_user(self):
        """Test user with only required fields."""
        user = TelegramUser(id=123, first_name="Test")
        assert user.id == 123
        assert user.first_name == "Test"
        assert user.last_name is None
        assert user.username is None
    
    def test_full_user(self):
        """Test user with all fields."""
        user = TelegramUser(
            id=123,
            first_name="Test",
            last_name="User",
            username="testuser",
            language_code="en",
            is_premium=True,
        )
        assert user.id == 123
        assert user.first_name == "Test"
        assert user.last_name == "User"
        assert user.username == "testuser"
        assert user.language_code == "en"
        assert user.is_premium is True


# ---------------------------------------------------------------------------
# Tests: InitData
# ---------------------------------------------------------------------------

class TestInitData:
    """Tests for InitData model."""
    
    def test_minimal_init_data(self):
        """Test InitData with only required fields."""
        data = InitData(auth_date=1234567890, hash="abc123")
        assert data.auth_date == 1234567890
        assert data.hash == "abc123"
        assert data.user is None
    
    def test_full_init_data(self):
        """Test InitData with all fields."""
        user = TelegramUser(id=123, first_name="Test")
        data = InitData(
            user=user,
            chat_instance="12345",
            chat_type="private",
            auth_date=1234567890,
            hash="abc123",
            query_id="xyz789",
            start_param="signal_abc",
        )
        assert data.user.id == 123
        assert data.chat_instance == "12345"
        assert data.chat_type == "private"
        assert data.query_id == "xyz789"
        assert data.start_param == "signal_abc"


# ---------------------------------------------------------------------------
# Tests: Read-Only Policy
# ---------------------------------------------------------------------------

class TestReadOnlyPolicy:
    """Tests to verify read-only policy in v1."""
    
    def test_no_dangerous_endpoints(self):
        """Verify no execution endpoints exist in v1."""
        from pearlalgo.miniapp.server import app
        
        # Get all routes
        routes = [route.path for route in app.routes]
        
        # These endpoints should NOT exist in v1
        dangerous_patterns = [
            "/api/arm",
            "/api/disarm",
            "/api/kill",
            "/api/execute",
            "/api/trade",
            "/api/order",
        ]
        
        for pattern in dangerous_patterns:
            for route in routes:
                assert pattern not in route, f"Dangerous endpoint found: {route}"
    
    def test_notes_endpoint_is_only_write(self):
        """Verify notes is the only write endpoint (for journaling)."""
        from pearlalgo.miniapp.server import app
        
        # Find POST endpoints
        post_routes = []
        for route in app.routes:
            if hasattr(route, 'methods') and 'POST' in route.methods:
                post_routes.append(route.path)
        
        # Only /api/notes should accept POST
        assert len(post_routes) == 1, f"Expected 1 POST route, found: {post_routes}"
        assert "/api/notes" in post_routes


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestAuthIntegration:
    """Integration tests for auth flow."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint_no_auth(self):
        """Test that health endpoint doesn't require auth."""
        from fastapi.testclient import TestClient
        from pearlalgo.miniapp.server import app
        
        client = TestClient(app)
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
    
    @pytest.mark.asyncio
    async def test_status_endpoint_requires_auth(self):
        """Test that status endpoint requires auth."""
        from fastapi.testclient import TestClient
        from pearlalgo.miniapp.server import app
        
        client = TestClient(app)
        response = client.get("/api/status")
        
        # Should fail without auth header
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_signals_endpoint_requires_auth(self):
        """Test that signals endpoint requires auth."""
        from fastapi.testclient import TestClient
        from pearlalgo.miniapp.server import app
        
        client = TestClient(app)
        response = client.get("/api/signals")
        
        # Should fail without auth header
        assert response.status_code == 401





