#!/usr/bin/env python3
"""Initialize default user credentials for the OpenStack Simulator.

Every application credential ID owns an isolated environment whose project is
``<credential_id>-project``. The secret of a credential is the SHA-256 hex
digest of its ID, so no credential needs to be stored.
"""

import os

from openstack_simulator.credentials import (
    DEFAULT_CREDENTIAL_ID,
    credential_secret,
)
from openstack_simulator.environments import EnvironmentRegistry


def init_default_user() -> None:
    """Create the default environment and prove its credential works."""
    credential_id = os.getenv("DEFAULT_CREDENTIAL_ID", DEFAULT_CREDENTIAL_ID)
    secret = credential_secret(credential_id)

    print(f"Initializing default application credential: {credential_id}")
    print(f"Project: {credential_id}-project")

    registry = EnvironmentRegistry()
    try:
        token, environment = registry.authenticate(credential_id, secret)
    except Exception as exc:  # noqa: BLE001 - startup must fail loudly
        print(f"Failed to initialize default credential: {exc}")
        raise

    print(f"Project: {environment.project_name} ({environment.project_id})")
    print(f"Secret (SHA-256 of the id): {secret}")
    print(f"Default user initialized with token ID: {token.id}")


if __name__ == "__main__":
    init_default_user()
