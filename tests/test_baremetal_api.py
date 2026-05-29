"""Integration tests for the Ironic Baremetal REST API endpoints.

Tests cover:
- Node CRUD endpoints (GET, POST, PATCH, DELETE)
- Node state transitions (power, provision)
- Port CRUD endpoints (GET, POST, DELETE)
- Authentication enforcement
- Error responses (404, 409, 413)

Requirements: 11.1–11.15, 8.1–8.8, 12.5
"""

import pytest

from openstack_simulator.api.app import create_app


@pytest.fixture
def client():
    """Create a Flask test client with a fresh simulator."""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def auth_token(client):
    """Get a valid auth token for authenticated requests."""
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


def _headers(token):
    """Build request headers with auth token."""
    return {"X-Auth-Token": token, "Content-Type": "application/json"}


class TestNodeEndpoints:
    """Integration tests for baremetal node endpoints."""

    def test_create_node_returns_201(self, client, auth_token):
        resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "test-node-1",
            "driver": "ipmi",
            "memory_mb": 8192,
            "cpus": 4,
            "local_gb": 500,
            "cpu_arch": "x86_64",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "test-node-1"
        assert data["driver"] == "ipmi"
        assert data["provision_state"] == "enroll"
        assert data["power_state"] == "power off"
        assert "id" in data
        assert "created_at" in data

    def test_list_nodes_returns_active_nodes(self, client, auth_token):
        # Create two nodes
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "node-a", "driver": "ipmi"
        })
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "node-b", "driver": "fake"
        })

        resp = client.get("/baremetal/v1/nodes", headers=_headers(auth_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["nodes"]) == 2
        names = [n["name"] for n in data["nodes"]]
        assert "node-a" in names
        assert "node-b" in names

    def test_get_node_by_name(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "my-node", "driver": "ipmi"
        })

        resp = client.get("/baremetal/v1/nodes/my-node", headers=_headers(auth_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "my-node"

    def test_get_node_by_uuid(self, client, auth_token):
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "uuid-node", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        resp = client.get(f"/baremetal/v1/nodes/{node_id}", headers=_headers(auth_token))
        assert resp.status_code == 200
        assert resp.get_json()["id"] == node_id

    def test_get_node_not_found_returns_404(self, client, auth_token):
        resp = client.get("/baremetal/v1/nodes/nonexistent", headers=_headers(auth_token))
        assert resp.status_code == 404

    def test_patch_node_updates_properties(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "patch-node", "driver": "ipmi", "memory_mb": 4096
        })

        resp = client.patch("/baremetal/v1/nodes/patch-node", headers=_headers(auth_token), json={
            "memory_mb": 16384, "cpus": 8
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["memory_mb"] == 16384
        assert data["cpus"] == 8

    def test_patch_node_not_found_returns_404(self, client, auth_token):
        resp = client.patch("/baremetal/v1/nodes/ghost", headers=_headers(auth_token), json={
            "memory_mb": 1024
        })
        assert resp.status_code == 404

    def test_patch_node_duplicate_name_returns_409(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "node-x", "driver": "ipmi"
        })
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "node-y", "driver": "ipmi"
        })

        resp = client.patch("/baremetal/v1/nodes/node-y", headers=_headers(auth_token), json={
            "name": "node-x"
        })
        assert resp.status_code == 409

    def test_delete_node_returns_204(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "del-node", "driver": "ipmi"
        })

        resp = client.delete("/baremetal/v1/nodes/del-node", headers=_headers(auth_token))
        assert resp.status_code == 204

        # Verify node is gone from listing
        list_resp = client.get("/baremetal/v1/nodes", headers=_headers(auth_token))
        names = [n["name"] for n in list_resp.get_json()["nodes"]]
        assert "del-node" not in names

    def test_delete_node_not_found_returns_404(self, client, auth_token):
        resp = client.delete("/baremetal/v1/nodes/ghost", headers=_headers(auth_token))
        assert resp.status_code == 404

    def test_provision_state_transition_returns_202(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "prov-node", "driver": "ipmi"
        })

        # enroll -> manageable
        resp = client.put("/baremetal/v1/nodes/prov-node/states/provision",
                          headers=_headers(auth_token), json={"target": "manage"})
        assert resp.status_code == 202

        # Verify state changed
        get_resp = client.get("/baremetal/v1/nodes/prov-node", headers=_headers(auth_token))
        assert get_resp.get_json()["provision_state"] == "manageable"

    def test_invalid_provision_transition_returns_409(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "bad-prov", "driver": "ipmi"
        })

        # enroll -> "active" is invalid
        resp = client.put("/baremetal/v1/nodes/bad-prov/states/provision",
                          headers=_headers(auth_token), json={"target": "active"})
        assert resp.status_code == 409

    def test_power_state_change_returns_202(self, client, auth_token):
        # Create node and transition to available state
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "power-node", "driver": "ipmi"
        })
        client.put("/baremetal/v1/nodes/power-node/states/provision",
                   headers=_headers(auth_token), json={"target": "manage"})
        client.put("/baremetal/v1/nodes/power-node/states/provision",
                   headers=_headers(auth_token), json={"target": "provide"})

        # Now power on
        resp = client.put("/baremetal/v1/nodes/power-node/states/power",
                          headers=_headers(auth_token), json={"target": "power on"})
        assert resp.status_code == 202

        # Verify power state
        get_resp = client.get("/baremetal/v1/nodes/power-node", headers=_headers(auth_token))
        assert get_resp.get_json()["power_state"] == "power on"

    def test_invalid_power_state_returns_409(self, client, auth_token):
        # Node in enroll state cannot change power
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "no-power", "driver": "ipmi"
        })

        resp = client.put("/baremetal/v1/nodes/no-power/states/power",
                          headers=_headers(auth_token), json={"target": "power on"})
        assert resp.status_code == 409

    def test_duplicate_node_returns_409(self, client, auth_token):
        client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "dup-node", "driver": "ipmi"
        })

        resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "dup-node", "driver": "fake"
        })
        assert resp.status_code == 409

    def test_node_quota_exceeded_returns_413(self, client, auth_token):
        # Default limit is 10 nodes — create 10 then try one more
        for i in range(10):
            resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
                "name": f"quota-node-{i}", "driver": "ipmi"
            })
            assert resp.status_code == 201

        resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "quota-node-overflow", "driver": "ipmi"
        })
        assert resp.status_code == 413

    def test_authentication_required(self, client):
        """All endpoints require a valid auth token."""
        resp = client.get("/baremetal/v1/nodes")
        assert resp.status_code == 401

        resp = client.post("/baremetal/v1/nodes", json={"name": "x", "driver": "y"})
        assert resp.status_code == 401

        resp = client.delete("/baremetal/v1/nodes/x")
        assert resp.status_code == 401

        resp = client.put("/baremetal/v1/nodes/x/states/power", json={"target": "power on"})
        assert resp.status_code == 401


class TestPortEndpoints:
    """Integration tests for baremetal port endpoints."""

    def test_create_port_returns_201(self, client, auth_token):
        # Create a node first
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "port-host", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "aa:bb:cc:dd:ee:01"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["node_id"] == node_id
        assert data["address"] == "aa:bb:cc:dd:ee:01"
        assert "id" in data

    def test_list_ports_returns_all(self, client, auth_token):
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "list-port-host", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "11:22:33:44:55:01"
        })
        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "11:22:33:44:55:02"
        })

        resp = client.get("/baremetal/v1/ports", headers=_headers(auth_token))
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["ports"]) == 2

    def test_list_ports_filtered_by_node_id(self, client, auth_token):
        # Create two nodes
        resp1 = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "filter-host-1", "driver": "ipmi"
        })
        resp2 = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "filter-host-2", "driver": "ipmi"
        })
        node_id_1 = resp1.get_json()["id"]
        node_id_2 = resp2.get_json()["id"]

        # Create ports on each node
        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id_1, "address": "aa:11:22:33:44:01"
        })
        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id_1, "address": "aa:11:22:33:44:02"
        })
        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id_2, "address": "bb:11:22:33:44:01"
        })

        # Filter by node_id_1
        resp = client.get(f"/baremetal/v1/ports?node_id={node_id_1}", headers=_headers(auth_token))
        assert resp.status_code == 200
        ports = resp.get_json()["ports"]
        assert len(ports) == 2
        assert all(p["node_id"] == node_id_1 for p in ports)

    def test_delete_port_returns_204(self, client, auth_token):
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "del-port-host", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        port_resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "cc:dd:ee:ff:00:01"
        })
        port_id = port_resp.get_json()["id"]

        resp = client.delete(f"/baremetal/v1/ports/{port_id}", headers=_headers(auth_token))
        assert resp.status_code == 204

        # Verify port is gone
        list_resp = client.get("/baremetal/v1/ports", headers=_headers(auth_token))
        assert len(list_resp.get_json()["ports"]) == 0

    def test_delete_port_not_found_returns_404(self, client, auth_token):
        resp = client.delete("/baremetal/v1/ports/nonexistent-id", headers=_headers(auth_token))
        assert resp.status_code == 404

    def test_create_port_invalid_node_returns_404(self, client, auth_token):
        resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": "nonexistent-node-id", "address": "aa:bb:cc:dd:ee:ff"
        })
        assert resp.status_code == 404

    def test_create_port_duplicate_mac_returns_409(self, client, auth_token):
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "dup-mac-host", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "ff:ee:dd:cc:bb:aa"
        })

        resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "ff:ee:dd:cc:bb:aa"
        })
        assert resp.status_code == 409

    def test_port_quota_exceeded_returns_413(self, client, auth_token):
        # Default limit is 20 ports
        create_resp = client.post("/baremetal/v1/nodes", headers=_headers(auth_token), json={
            "name": "quota-port-host", "driver": "ipmi"
        })
        node_id = create_resp.get_json()["id"]

        for i in range(20):
            resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
                "node_id": node_id, "address": f"aa:bb:cc:dd:{i:02x}:01"
            })
            assert resp.status_code == 201

        resp = client.post("/baremetal/v1/ports", headers=_headers(auth_token), json={
            "node_id": node_id, "address": "aa:bb:cc:dd:ff:ff"
        })
        assert resp.status_code == 413
