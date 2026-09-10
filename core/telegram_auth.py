import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger("telegram_auth")

# In-memory storage for short-lived magic links: {token: (user_id, expires_at)}
_MAGIC_LINKS: Dict[str, Tuple[int, float]] = {}
MAGIC_LINK_TTL = 300  # 5 minutes


def validate_telegram_init_data(init_data: str, bot_token: str) -> Tuple[bool, Optional[dict]]:
    """
    Validates Telegram WebApp initData string using HMAC-SHA256 according to Telegram's documentation:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        return False, None

    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed:
            return False, None

        received_hash = parsed.pop("hash")

        # Sort all remaining pairs alphabetically by key and join with newline
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

        # Secret key is HMAC-SHA256 of bot_token using "WebAppData"
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

        # Calculate HMAC-SHA256 hash of data_check_string using secret_key
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.warning("Telegram WebApp initData hash mismatch.")
            return False, None

        user_data = None
        if "user" in parsed:
            try:
                user_data = json.loads(parsed["user"])
            except Exception as e:
                logger.error(f"Error parsing user JSON from initData: {e}")

        return True, user_data
    except Exception as e:
        logger.error(f"Failed to validate initData: {e}")
        return False, None


def create_magic_link_token(user_id: int) -> str:
    """Generates a secure, short-lived token for 1-click browser login."""
    _cleanup_expired_tokens()
    token = secrets.token_urlsafe(32)
    _MAGIC_LINKS[token] = (user_id, time.time() + MAGIC_LINK_TTL)
    return token


def consume_magic_link_token(token: str) -> Optional[int]:
    """Consumes and invalidates a magic link token, returning the user_id if valid."""
    _cleanup_expired_tokens()
    if token in _MAGIC_LINKS:
        user_id, expires_at = _MAGIC_LINKS.pop(token)
        if time.time() <= expires_at:
            return user_id
    return None


def _cleanup_expired_tokens():
    """Removes stale expired tokens from memory."""
    now = time.time()
    expired_keys = [k for k, (_, exp) in _MAGIC_LINKS.items() if exp < now]
    for k in expired_keys:
        _MAGIC_LINKS.pop(k, None)
