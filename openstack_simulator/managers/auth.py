"""Simulated Keystone authentication manager."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from openstack_simulator.exceptions import (
    AuthenticationError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from openstack_simulator.models import Token
from openstack_simulator.store import ResourceStore


class AuthManager:
    """Simulated Keystone authentication manager."""

    def __init__(self, store: ResourceStore, session_timeout: int = 120) -> None:
        self.store = store
        self.session_timeout = session_timeout  # minutes

    def authenticate(self, username: str, password: str) -> Token:
        """Authenticate a user and return a Token.

        Raises:
            AuthenticationError: If username or password is empty.
        """
        if not username or not password:
            raise AuthenticationError("Username and password must not be empty")

        token_id = str(uuid.uuid4())
        issued_at = datetime.utcnow().isoformat() + "Z"
        expires_at = (
            datetime.utcnow() + timedelta(minutes=self.session_timeout)
        ).isoformat() + "Z"

        token = Token(
            id=token_id,
            username=username,
            issued_at=issued_at,
            expires_at=expires_at,
        )

        self.store.tokens[token.id] = token
        return token

    def validate_token(self, token_id: str) -> bool:
        """Validate a token by its UUID string.

        Returns True if valid and not expired.

        Raises:
            ResourceNotFoundError: If the token UUID is unknown.
            TokenExpiredError: If the token has expired.
        """
        token = self.store.tokens.get(token_id)
        if token is None:
            raise ResourceNotFoundError(f"Token '{token_id}' not found")

        expires_at = datetime.fromisoformat(token.expires_at.rstrip("Z"))
        if datetime.utcnow() > expires_at:
            raise TokenExpiredError(f"Token '{token_id}' has expired")

        return True
