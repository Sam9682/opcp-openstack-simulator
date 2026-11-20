"""Per-credential environments (multi-user support).

Every application credential ID owns an isolated simulator environment: its
own store, clock, placement service, quotas and managers. State is never
shared between credentials, so two users of the same server see separate
OpenStack worlds.
"""

from __future__ import annotations

import threading
from typing import Mapping

from openstack_simulator.credentials import (
    DEFAULT_CREDENTIAL_ID,
    credential_secret,
    normalize_credential_id,
    verify_credential,
)
from openstack_simulator.exceptions import AuthenticationError
from openstack_simulator.models import Token
from openstack_simulator.simulator import Simulator


class EnvironmentRegistry:
    """Maps an application credential ID to its isolated ``Simulator``."""

    def __init__(self, config: Mapping | None = None) -> None:
        self.config = dict(config or {})
        self._lock = threading.RLock()
        self._environments: dict[str, Simulator] = {}

    def _create(self, credential_id: str) -> Simulator:
        environment = Simulator(self.config, credential_id=credential_id)
        self._environments[credential_id] = environment
        return environment

    def get(self, credential_id: object) -> Simulator:
        """Return the environment of ``credential_id``, creating it on first use.

        Raises:
            ValueError: If the credential ID is missing or unsafe.
        """
        normalized = normalize_credential_id(credential_id)
        with self._lock:
            environment = self._environments.get(normalized)
            if environment is None:
                environment = self._create(normalized)
            return environment

    @property
    def default(self) -> Simulator:
        """The environment of the built-in default credential."""
        return self.get(DEFAULT_CREDENTIAL_ID)

    def environments(self) -> dict[str, Simulator]:
        """Snapshot of the registered credential ID to environment mapping."""
        with self._lock:
            return dict(self._environments)

    def authenticate(
        self, credential_id: object, secret: object
    ) -> tuple[Token, Simulator]:
        """Authenticate an application credential in its own environment.

        The secret must be the SHA-256 hex digest of the credential ID.

        Raises:
            AuthenticationError: If the ID or secret is invalid.
        """
        try:
            normalized = normalize_credential_id(credential_id)
        except ValueError as exc:
            raise AuthenticationError(str(exc)) from None
        if not verify_credential(normalized, secret):
            raise AuthenticationError(
                "Invalid application credential: the secret must be the "
                f"SHA-256 digest of the application credential id "
                f"(expected {credential_secret(normalized)})"
            )
        environment = self.get(normalized)
        token = environment.auth_manager.authenticate(
            normalized, credential_secret(normalized)
        )
        return token, environment

    def environment_for_token(self, token_id: str) -> Simulator | None:
        """Return the environment that issued ``token_id``, if any."""
        with self._lock:
            for environment in self._environments.values():
                if token_id in environment.store.tokens:
                    return environment
        return None

    def reset(self) -> None:
        """Clear every environment and drop the non-default ones."""
        with self._lock:
            for environment in self._environments.values():
                environment.reset()
            self._environments = {
                key: value
                for key, value in self._environments.items()
                if key == DEFAULT_CREDENTIAL_ID
            }
