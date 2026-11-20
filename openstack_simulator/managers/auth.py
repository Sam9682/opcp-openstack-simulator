"""Simulated Keystone authentication manager."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from openstack_simulator.credentials import (
    DEFAULT_CREDENTIAL_ID,
    normalize_credential_id,
    project_id_for,
    verify_credential,
)
from openstack_simulator.exceptions import (
    AuthenticationError,
    ResourceNotFoundError,
    TokenExpiredError,
)
from openstack_simulator.models import Token
from openstack_simulator.store import ResourceStore

_SECRET_RULE = (
    "Invalid application credential: the secret must be the SHA-256 hex "
    "digest of the application credential id"
)


class AuthManager:
    """Simulated Keystone authentication manager.

    Authentication accepts an application credential ID whose secret is the
    SHA-256 hex digest of that ID. The token is bound to the credential's own
    project, so each credential sees an isolated environment.

    Password authentication stays available for tooling: any non-empty
    username and password work, and the token is bound to this environment's
    project.
    """

    def __init__(
        self,
        store: ResourceStore,
        session_timeout: int = 120,
        credential_id: str = DEFAULT_CREDENTIAL_ID,
    ) -> None:
        self.store = store
        self.session_timeout = session_timeout  # minutes
        self.credential_id = normalize_credential_id(credential_id)
        self.project_id = project_id_for(self.credential_id)

    def _issue(self, username: str) -> Token:
        now = datetime.utcnow()
        token = Token(
            id=str(uuid.uuid4()),
            username=username,
            issued_at=now.isoformat() + "Z",
            expires_at=(now + timedelta(minutes=self.session_timeout)).isoformat()
            + "Z",
            project_id=self.project_id,
        )
        self.store.tokens[token.id] = token
        return token

    def authenticate(self, username: str, password: str) -> Token:
        """Authenticate a user and return a Token.

        When ``username`` is this environment's credential ID, ``password``
        must be its SHA-256 digest. Any other non-empty pair is accepted as
        password authentication.

        Raises:
            AuthenticationError: If username or password is empty, or if the
                username is the credential ID with a wrong secret.
        """
        if not username or not password:
            raise AuthenticationError("Username and password must not be empty")
        if username == self.credential_id and not verify_credential(
            username, password
        ):
            raise AuthenticationError(_SECRET_RULE)
        return self._issue(username)

    def authenticate_application_credential(
        self, credential_id: str, secret: str
    ) -> Token:
        """Authenticate an application credential ID and its digest secret.

        Raises:
            AuthenticationError: If the credential belongs to another
                environment or the secret is not its digest.
        """
        if credential_id != self.credential_id:
            raise AuthenticationError(
                f"Application credential '{credential_id}' is not known here"
            )
        if not verify_credential(credential_id, secret):
            raise AuthenticationError(_SECRET_RULE)
        return self._issue(credential_id)

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
