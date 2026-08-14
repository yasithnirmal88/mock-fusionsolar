
"""
Simple replaceable authentication service for the MVP.

This module implements a fake authentication provider that accepts any
username/password and issues a bearer token. Tokens are stored in-memory with
an expiry. The service exposes a validate_token method used as a FastAPI
dependency to protect endpoints. The implementation is intentionally simple
and designed to be replaced by a real auth provider in the future.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid
from typing import Dict, Optional

from fastapi import HTTPException, status
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TokenRecord:
    token: str
    username: str
    expires_at: datetime


class AuthService:
    """In-memory fake auth service.

    Methods:
        - login(username, password) -> token
        - validate_token(token) -> username or raise HTTPException
    """

    def __init__(self, token_ttl_seconds: int = 3600) -> None:
        self._tokens: Dict[str, TokenRecord] = {}
        self._ttl = timedelta(seconds=token_ttl_seconds)

    def login(self, username: str, password: str) -> str:
        """Accept any username/password and return a bearer token.

        The token is a uuid4 string stored with an expiry.
        """
        token = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + self._ttl
        self._tokens[token] = TokenRecord(token=token, username=username, expires_at=expires_at)
        logger.info("Issued token for user=%s expires_at=%s", username, expires_at.isoformat())
        return token

    def validate_token(self, token: Optional[str]) -> str:
        """Validate the provided bearer token and return username.

        Raise HTTPException with 401 status if token is missing or invalid.
        """
        if not token:
            logger.debug("Missing token")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

        record = self._tokens.get(token)
        if not record:
            logger.debug("Invalid token: %s", token)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

        if datetime.now(timezone.utc) >= record.expires_at:
            logger.debug("Expired token for user=%s", record.username)
            # Remove expired token
            del self._tokens[token]
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

        return record.username


# Module-level instance for convenience. Can be replaced in DI for testing.
auth_service = AuthService()
