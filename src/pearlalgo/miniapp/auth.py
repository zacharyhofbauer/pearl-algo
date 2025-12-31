"""
Telegram Mini App Authentication

Validates Telegram WebApp initData and enforces access control.

References:
- https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from pydantic import BaseModel


class TelegramUser(BaseModel):
    """Telegram user from initData."""
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None


class InitData(BaseModel):
    """Parsed and validated Telegram initData."""
    user: Optional[TelegramUser] = None
    chat_instance: Optional[str] = None
    chat_type: Optional[str] = None
    auth_date: int
    hash: str
    query_id: Optional[str] = None
    start_param: Optional[str] = None


class AuthError(Exception):
    """Authentication error."""
    pass


class InitDataValidator:
    """
    Validates Telegram Mini App initData.
    
    The validation process:
    1. Parse the initData query string
    2. Extract the hash
    3. Build the data-check-string (sorted key=value pairs)
    4. Compute HMAC-SHA256 using secret_key = HMAC-SHA256("WebAppData", bot_token)
    5. Compare computed hash with provided hash
    """
    
    # initData is valid for 24 hours by default
    DEFAULT_MAX_AGE_SECONDS = 86400
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        allowed_user_id: Optional[int] = None,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ):
        """
        Initialize validator.
        
        Args:
            bot_token: Telegram bot token (defaults to TELEGRAM_BOT_TOKEN env var)
            allowed_user_id: If set, only this user ID is allowed (me-only mode)
            max_age_seconds: Maximum age of initData in seconds
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        
        # Compute the secret key once
        self._secret_key = hmac.new(
            b"WebAppData",
            self.bot_token.encode(),
            hashlib.sha256
        ).digest()
        
        self.allowed_user_id = allowed_user_id
        self.max_age_seconds = max_age_seconds
    
    def validate(self, init_data_raw: str) -> InitData:
        """
        Validate initData string.
        
        Args:
            init_data_raw: Raw initData query string from Telegram WebApp
            
        Returns:
            Parsed InitData object
            
        Raises:
            AuthError: If validation fails
        """
        if not init_data_raw:
            raise AuthError("Empty initData")
        
        # Parse query string
        try:
            parsed = parse_qs(init_data_raw, keep_blank_values=True)
        except Exception as e:
            raise AuthError(f"Failed to parse initData: {e}")
        
        # Extract hash
        hash_list = parsed.pop("hash", None)
        if not hash_list:
            raise AuthError("Missing hash in initData")
        provided_hash = hash_list[0]
        
        # Build data-check-string (sorted key=value pairs, newline separated)
        # Values need to be URL-decoded
        data_items = []
        for key in sorted(parsed.keys()):
            values = parsed[key]
            value = values[0] if values else ""
            # URL decode the value
            decoded_value = unquote(value)
            data_items.append(f"{key}={decoded_value}")
        
        data_check_string = "\n".join(data_items)
        
        # Compute HMAC-SHA256
        computed_hash = hmac.new(
            self._secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare hashes (constant-time comparison)
        if not hmac.compare_digest(computed_hash, provided_hash):
            raise AuthError("Invalid initData signature")
        
        # Parse the data
        try:
            init_data = self._parse_init_data(parsed, provided_hash)
        except Exception as e:
            raise AuthError(f"Failed to parse initData fields: {e}")
        
        # Check age
        now = int(time.time())
        age = now - init_data.auth_date
        if age > self.max_age_seconds:
            raise AuthError(f"initData expired ({age}s old, max {self.max_age_seconds}s)")
        if age < -60:  # Allow 1 minute clock skew
            raise AuthError(f"initData from the future ({-age}s ahead)")
        
        # Check user access (me-only mode)
        if self.allowed_user_id is not None:
            if init_data.user is None:
                raise AuthError("No user in initData")
            if init_data.user.id != self.allowed_user_id:
                raise AuthError(f"User {init_data.user.id} not authorized")
        
        return init_data
    
    def _parse_init_data(self, parsed: dict, hash_value: str) -> InitData:
        """Parse the initData fields into an InitData object."""
        # Parse user JSON if present
        user = None
        user_list = parsed.get("user")
        if user_list:
            user_json = unquote(user_list[0])
            user_dict = json.loads(user_json)
            user = TelegramUser(**user_dict)
        
        # Parse auth_date
        auth_date_list = parsed.get("auth_date")
        if not auth_date_list:
            raise AuthError("Missing auth_date in initData")
        auth_date = int(auth_date_list[0])
        
        # Parse optional fields
        chat_instance = None
        chat_instance_list = parsed.get("chat_instance")
        if chat_instance_list:
            chat_instance = chat_instance_list[0]
        
        chat_type = None
        chat_type_list = parsed.get("chat_type")
        if chat_type_list:
            chat_type = chat_type_list[0]
        
        query_id = None
        query_id_list = parsed.get("query_id")
        if query_id_list:
            query_id = query_id_list[0]
        
        start_param = None
        start_param_list = parsed.get("start_param")
        if start_param_list:
            start_param = start_param_list[0]
        
        return InitData(
            user=user,
            chat_instance=chat_instance,
            chat_type=chat_type,
            auth_date=auth_date,
            hash=hash_value,
            query_id=query_id,
            start_param=start_param,
        )


def get_validator() -> InitDataValidator:
    """
    Get a configured InitDataValidator instance.
    
    Uses environment variables:
    - TELEGRAM_BOT_TOKEN: Bot token for signature validation
    - TELEGRAM_CHAT_ID: If set, enables me-only mode
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    
    # Get allowed user ID (me-only mode)
    allowed_user_id = None
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        try:
            allowed_user_id = int(chat_id)
        except ValueError:
            pass  # Non-numeric chat ID (group?), don't restrict
    
    return InitDataValidator(
        bot_token=bot_token,
        allowed_user_id=allowed_user_id,
    )


