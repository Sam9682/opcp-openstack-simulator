"""Application credential rules for the simulator.

An application credential is identified by an ID. Its secret is the
lowercase SHA-256 hex digest of that ID, so a credential can be created
without storing any state: anyone who knows the ID can derive the secret.
Every credential ID owns an isolated environment and a project named
``<credential_id>-project``.
"""

from __future__ import annotations

import hashlib
import hmac
import re

DEFAULT_CREDENTIAL_ID = "simulator"
PROJECT_SUFFIX = "-project"

# Credential IDs become project names, so only path-safe characters are allowed.
_CREDENTIAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def normalize_credential_id(credential_id: object) -> str:
    """Return the canonical credential ID.

    Raises:
        ValueError: If the value is missing or contains unsafe characters.
    """
    if not isinstance(credential_id, str) or not credential_id.strip():
        raise ValueError(f"Invalid application credential id: {credential_id!r}")
    value = credential_id.strip()
    if not _CREDENTIAL_ID_RE.match(value):
        raise ValueError(f"Invalid application credential id: {value!r}")
    return value


def credential_secret(credential_id: str) -> str:
    """SHA-256 hex digest of ``credential_id`` (the expected secret)."""
    return hashlib.sha256(credential_id.encode("utf-8")).hexdigest()


def verify_credential(credential_id: str, secret: object) -> bool:
    """True when ``secret`` is the SHA-256 digest of ``credential_id``.

    The comparison is constant-time and case-insensitive for the digest.
    """
    if not isinstance(credential_id, str) or not isinstance(secret, str):
        return False
    expected = credential_secret(credential_id)
    return hmac.compare_digest(expected, secret.strip().lower())


def project_name_for(credential_id: str) -> str:
    """Project name owned by a credential: ``<credential_id>-project``."""
    return f"{credential_id}{PROJECT_SUFFIX}"


#: Project ID kept for the default credential so existing clients keep working.
LEGACY_PROJECT_ID = "fake-project-id-00000000001"


def project_id_for(credential_id: str) -> str:
    """Stable project ID for a credential.

    The default credential keeps the legacy project ID; every other
    credential gets a deterministic 32-character hexadecimal ID.
    """
    if credential_id == DEFAULT_CREDENTIAL_ID:
        return LEGACY_PROJECT_ID
    return hashlib.sha256(f"project:{credential_id}".encode("utf-8")).hexdigest()[:32]


DEFAULT_CREDENTIAL_SECRET = credential_secret(DEFAULT_CREDENTIAL_ID)
DEFAULT_PROJECT_NAME = project_name_for(DEFAULT_CREDENTIAL_ID)
DEFAULT_PROJECT_ID = project_id_for(DEFAULT_CREDENTIAL_ID)
