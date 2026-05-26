"""Smoke test for the OpenStack-compatible REST API."""

import json
import pytest

from openstack_simulator.api.app import create_app


@pytest.fixture
def client():
    """Create a Flask test client."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_token(client):
    """Get a valid auth token."""
    resp = client.post("/identity/v3/auth/tokens", json={
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {
                    "id": "simulator-app-credential",
                    "secret": "simulator-secret",
                },
            }
        }
    })
    assert resp.status_code == 201
    return resp.headers["X-Subject-Token"]


class TestIdentityAPI:
    """Test Keystone Identity API endpoints."""

    def test_version_discovery(self, client):
        resp = client.get("/identity/v3/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["version"]["id"] == "v3.14"
        assert data["version"]["status"] == "stable"

    def test_create_token_password(self, client):
        resp = client.post("/identity/v3/auth/tokens", json={
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": "admin",
                            "domain": {"id": "default"},
                            "password": "secret",
                        }
                    },
                }
            }
        })
        assert resp.status_code == 201
        assert "X-Subject-Token" in resp.headers
        data = resp.get_json()
        assert "token" in data
        assert "catalog" in data["token"]
        assert len(data["token"]["catalog"]) == 4

    def test_create_token_application_credential(self, client):
        resp = client.post("/identity/v3/auth/tokens", json={
            "auth": {
                "identity": {
                    "methods": ["application_credential"],
                    "application_credential": {
                        "id": "my-app-cred",
                        "secret": "my-secret",
                    },
                }
            }
        })
        assert resp.status_code == 201
        assert "X-Subject-Token" in resp.headers

    def test_validate_token(self, client, auth_token):
        resp = client.get("/identity/v3/auth/tokens", headers={
            "X-Auth-Token": auth_token,
            "X-Subject-Token": auth_token,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data

    def test_check_token_head(self, client, auth_token):
        resp = client.head("/identity/v3/auth/tokens", headers={
            "X-Auth-Token": auth_token,
            "X-Subject-Token": auth_token,
        })
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, client):
        resp = client.get("/compute/v2.1/servers", headers={
            "X-Auth-Token": "invalid-token-id",
        })
        assert resp.status_code == 401


class TestComputeAPI:
    """Test Nova Compute API endpoints."""

    def test_list_servers_empty(self, client, auth_token):
        resp = client.get("/compute/v2.1/servers", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["servers"] == []

    def test_create_server(self, client, auth_token):
        resp = client.post("/compute/v2.1/servers", json={
            "server": {"name": "test-vm", "flavorRef": "m1.small", "imageRef": "ubuntu-22.04"}
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["server"]["name"] == "test-vm"
        assert data["server"]["status"] == "ACTIVE"

    def test_get_server(self, client, auth_token):
        # Create first
        client.post("/compute/v2.1/servers", json={
            "server": {"name": "get-vm", "flavorRef": "m1.small", "imageRef": "ubuntu-22.04"}
        }, headers={"X-Auth-Token": auth_token})

        resp = client.get("/compute/v2.1/servers/get-vm", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        assert resp.get_json()["server"]["name"] == "get-vm"

    def test_delete_server(self, client, auth_token):
        client.post("/compute/v2.1/servers", json={
            "server": {"name": "del-vm", "flavorRef": "m1.small", "imageRef": "ubuntu-22.04"}
        }, headers={"X-Auth-Token": auth_token})

        resp = client.delete("/compute/v2.1/servers/del-vm", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 204

    def test_list_flavors(self, client, auth_token):
        resp = client.get("/compute/v2.1/flavors", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        assert len(resp.get_json()["flavors"]) == 5

    def test_list_images(self, client, auth_token):
        resp = client.get("/compute/v2.1/images", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        assert len(resp.get_json()["images"]) == 4


class TestNetworkAPI:
    """Test Neutron Network API endpoints."""

    def test_create_and_list_network(self, client, auth_token):
        resp = client.post("/network/v2.0/networks", json={
            "network": {"name": "test-net"}
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 201
        net = resp.get_json()["network"]
        assert net["name"] == "test-net"
        assert net["status"] == "ACTIVE"

        resp = client.get("/network/v2.0/networks", headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        assert len(resp.get_json()["networks"]) == 1

    def test_create_subnet(self, client, auth_token):
        # Create network first
        resp = client.post("/network/v2.0/networks", json={
            "network": {"name": "subnet-net"}
        }, headers={"X-Auth-Token": auth_token})
        net_id = resp.get_json()["network"]["id"]

        resp = client.post("/network/v2.0/subnets", json={
            "subnet": {"network_id": net_id, "name": "my-subnet", "cidr": "10.0.0.0/24", "gateway_ip": "10.0.0.1"}
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 201
        subnet = resp.get_json()["subnet"]
        assert subnet["name"] == "my-subnet"
        assert subnet["cidr"] == "10.0.0.0/24"

    def test_create_security_group_and_rule(self, client, auth_token):
        resp = client.post("/network/v2.0/security-groups", json={
            "security_group": {"name": "web-sg", "description": "Allow HTTP"}
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 201
        sg = resp.get_json()["security_group"]
        sg_id = sg["id"]

        resp = client.post("/network/v2.0/security-group-rules", json={
            "security_group_rule": {
                "security_group_id": sg_id,
                "protocol": "tcp",
                "port_range_min": 80,
                "port_range_max": 80,
                "direction": "ingress",
                "remote_ip_prefix": "0.0.0.0/0",
            }
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 201
        rule = resp.get_json()["security_group_rule"]
        assert rule["protocol"] == "tcp"
        assert rule["port_range_min"] == 80


class TestVolumeAPI:
    """Test Cinder Volume API endpoints."""

    def test_create_and_list_volume(self, client, auth_token):
        resp = client.post("/volume/v3/fake-project-id-00000000001/volumes", json={
            "volume": {"name": "test-vol", "size": 10}
        }, headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 202
        vol = resp.get_json()["volume"]
        assert vol["name"] == "test-vol"
        assert vol["size"] == 10
        assert vol["status"] == "available"

        resp = client.get("/volume/v3/fake-project-id-00000000001/volumes",
                          headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 200
        assert len(resp.get_json()["volumes"]) == 1

    def test_delete_volume(self, client, auth_token):
        client.post("/volume/v3/fake-project-id-00000000001/volumes", json={
            "volume": {"name": "del-vol", "size": 5}
        }, headers={"X-Auth-Token": auth_token})

        resp = client.delete("/volume/v3/fake-project-id-00000000001/volumes/del-vol",
                             headers={"X-Auth-Token": auth_token})
        assert resp.status_code == 204
