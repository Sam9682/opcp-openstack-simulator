"""Multi-user application credential behavior.

Each application credential ID owns an isolated environment:
- the secret is the SHA-256 hex digest of the credential ID;
- the project is named ``<credential_id>-project``;
- resources created with one credential are invisible to another.
"""

from __future__ import annotations

import hashlib

import pytest

from openstack_simulator import EnvironmentRegistry, Simulator
from openstack_simulator.api.app import create_app
from openstack_simulator.credentials import (
    DEFAULT_CREDENTIAL_ID,
    LEGACY_PROJECT_ID,
    credential_secret,
    normalize_credential_id,
    project_id_for,
    project_name_for,
    verify_credential,
)
from openstack_simulator.exceptions import AuthenticationError


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------


def test_secret_is_sha256_of_credential_id():
    assert credential_secret("alice") == sha256("alice")
    assert verify_credential("alice", sha256("alice")) is True
    assert verify_credential("alice", sha256("alice").upper()) is True
    assert verify_credential("alice", "alice") is False
    assert verify_credential("alice", sha256("bob")) is False
    assert verify_credential("alice", None) is False


@pytest.mark.parametrize("bad", ["", "   ", "with space", "slash/admin", "../etc", 5, None])
def test_invalid_credential_ids_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_credential_id(bad)


def test_project_name_and_id_are_derived_from_credential():
    assert project_name_for("alice") == "alice-project"
    assert project_name_for("bob") == "bob-project"
    assert project_id_for("alice") != project_id_for("bob")
    # The default credential keeps the legacy project ID for compatibility.
    assert project_id_for(DEFAULT_CREDENTIAL_ID) == LEGACY_PROJECT_ID
    assert project_name_for(DEFAULT_CREDENTIAL_ID) == "simulator-project"


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------


def test_auth_manager_accepts_only_digest_secret():
    sim = Simulator({"time_scale": 0}, credential_id="alice")
    token = sim.auth_manager.authenticate_application_credential(
        "alice", sha256("alice")
    )
    assert token.project_id == sim.project_id
    with pytest.raises(AuthenticationError):
        sim.auth_manager.authenticate_application_credential("alice", "alice")
    with pytest.raises(AuthenticationError):
        sim.auth_manager.authenticate_application_credential("bob", sha256("bob"))


def test_auth_manager_token_is_bound_to_credential_project():
    sim = Simulator({"time_scale": 0}, credential_id="alice")
    token = sim.auth_manager.authenticate("admin", "admin")
    assert token.project_id == project_id_for("alice")


# ---------------------------------------------------------------------------
# EnvironmentRegistry
# ---------------------------------------------------------------------------


def test_registry_creates_isolated_environments():
    registry = EnvironmentRegistry({"time_scale": 0})
    alice, _ = registry.authenticate("alice", sha256("alice"))
    bob, _ = registry.authenticate("bob", sha256("bob"))
    assert alice.project_id != bob.project_id
    assert alice.project_id == project_id_for("alice")
    assert bob.project_id == project_id_for("bob")

    registry.get("alice").compute_manager.create("web", "m1.small", "ubuntu-22.04")
    assert len(registry.get("alice").compute_manager.list()) == 1
    assert registry.get("bob").compute_manager.list() == []


def test_registry_rejects_wrong_secret():
    registry = EnvironmentRegistry({"time_scale": 0})
    with pytest.raises(AuthenticationError):
        registry.authenticate("alice", "not-the-digest")


def test_registry_finds_environment_for_token():
    registry = EnvironmentRegistry({"time_scale": 0})
    token, _ = registry.authenticate("carol", sha256("carol"))
    environment = registry.environment_for_token(token.id)
    assert environment is not None
    assert environment.credential_id == "carol"
    assert registry.environment_for_token("unknown-token") is None


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app({"time_scale": 0})
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _auth(client, credential_id):
    resp = client.post(
        "/identity/v3/auth/tokens",
        json={
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": {
                        "id": credential_id,
                        "secret": sha256(credential_id),
                    },
                }
            }
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.headers["X-Subject-Token"], resp.get_json()["token"]


def test_token_reports_credential_project(client):
    token_id, token = _auth(client, "alice")
    assert token_id
    assert token["project"]["name"] == "alice-project"
    assert token["project"]["id"] == project_id_for("alice")


def test_wrong_secret_is_rejected(client):
    resp = client.post(
        "/identity/v3/auth/tokens",
        json={
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": {"id": "alice", "secret": "alice"},
                }
            }
        },
    )
    assert resp.status_code == 401


def test_each_credential_sees_only_its_own_resources(client):
    alice, _ = _auth(client, "alice")
    bob, _ = _auth(client, "bob")

    created = client.post(
        "/network/v2.0/networks",
        json={"network": {"name": "alice-net"}},
        headers={"X-Auth-Token": alice},
    )
    assert created.status_code == 201
    assert created.get_json()["network"]["tenant_id"] == project_id_for("alice")

    assert client.get(
        "/network/v2.0/networks", headers={"X-Auth-Token": alice}
    ).get_json()["networks"]
    assert (
        client.get("/network/v2.0/networks", headers={"X-Auth-Token": bob}).get_json()[
            "networks"
        ]
        == []
    )


def test_same_resource_name_allowed_in_two_environments(client):
    alice, _ = _auth(client, "alice")
    bob, _ = _auth(client, "bob")
    for token in (alice, bob):
        resp = client.post(
            "/volume/v3/x/volumes",
            json={"volume": {"name": "shared-name", "size": 1}},
            headers={"X-Auth-Token": token},
        )
        assert resp.status_code == 202


def test_projects_endpoint_lists_credential_project(client):
    alice, _ = _auth(client, "alice")
    resp = client.get("/identity/v3/projects", headers={"X-Auth-Token": alice})
    assert resp.status_code == 200
    projects = resp.get_json()["projects"]
    assert [p["name"] for p in projects] == ["alice-project"]
