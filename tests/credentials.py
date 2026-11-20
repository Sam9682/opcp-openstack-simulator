"""Shared application-credential helpers for the tests."""

from __future__ import annotations

from openstack_simulator.credentials import credential_secret

CREDENTIAL_ID = "simulator-app-credential"
CREDENTIAL_SECRET = credential_secret(CREDENTIAL_ID)


def credential_body(credential_id: str = CREDENTIAL_ID) -> dict:
    """Token request body for ``credential_id`` with its derived secret."""
    return {
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {
                    "id": credential_id,
                    "secret": credential_secret(credential_id),
                },
            }
        }
    }
