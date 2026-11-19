"""Exploration tests: server create must only schedule onto ``available`` nodes.

Replays ``openstack server create --flavor <f> --image ubuntu-22.04 my-server``
through the Flask test client and checks scenarios S0 to S10:

- S0: stock ``m1.small`` (no ``resources:`` extra spec), no nodes
- S1: bare-metal flavor, no nodes
- S2 to S8: a single node that is not schedulable
- S9: a pool of non-available nodes plus exactly one available node
- S10: a single available node

Scenarios S0 to S8 must answer HTTP 500 with the NoValidHost ``computeFault``
body, create no server and leave the simulator state unchanged.

Requirements: 1.12, 1.13, 2.12, 2.13, 2.14
"""

import copy
from dataclasses import asdict, is_dataclass

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from openstack_simulator.api.app import create_app

NO_VALID_HOST_BODY = {
    "computeFault": {
        "message": "No valid host was found. There are not enough hosts available.",
        "code": 500,
    }
}
RESOURCE_CLASS = "CUSTOM_BAREMETAL"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _login(client):
    """Authenticate with the application credential; remember the token."""
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
    token = resp.headers["X-Subject-Token"]
    client.environ_base["HTTP_X_AUTH_TOKEN"] = token
    return token


def _new_client():
    app = create_app({"time_scale": 0})
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def client():
    """Flask test client with a fresh simulator."""
    with _new_client() as c:
        yield c


@pytest.fixture
def auth_token(client):
    return _login(client)


def _headers(token):
    return {"X-Auth-Token": token, "Content-Type": "application/json"}


def _token(client):
    return client.environ_base["HTTP_X_AUTH_TOKEN"]


def _sim(client):
    return client.application.config["SIMULATOR"]


def _node(client, node_id):
    """Stored node by uuid (the store is keyed by name)."""
    return next(n for n in _sim(client).store.baremetal_nodes.values() if n.id == node_id)


def make_baremetal_flavor(client, name, resource_class=RESOURCE_CLASS):
    resp = client.post("/compute/v2.1/flavors", headers=_headers(_token(client)), json={
        "flavor": {
            "name": name, "id": name, "ram": 2048, "vcpus": 1, "disk": 20,
            "extra_specs": {f"resources:{resource_class}": "1"},
        }
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return name


def make_image(client, name="ubuntu-22.04"):
    """Register the image in the Image service and return its id."""
    resp = client.post("/image/v2/images", headers=_headers(_token(client)), json={
        "name": name, "disk_format": "qcow2", "container_format": "bare",
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _settle(client):
    resp = client.post("/_sim/settle", headers=_headers(_token(client)))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _provision(client, name, target):
    resp = client.put(f"/baremetal/v1/nodes/{name}/states/provision",
                      headers=_headers(_token(client)), json={"target": target})
    assert resp.status_code == 202, resp.get_data(as_text=True)


NODE_STATES = (
    "enroll", "manageable", "available", "active", "deploying", "cleaning",
    "maintenance", "instance_uuid", "last_error",
)


def make_node(client, name, state, resource_class=RESOURCE_CLASS):
    """Create a node (resource class CUSTOM_BAREMETAL, 100 GB) and drive it to ``state``.

    ``maintenance``, ``instance_uuid`` and ``last_error`` produce an
    ``available`` node with that disqualifying attribute. ``deploying`` and
    ``cleaning`` are set on the stored node because with ``time_scale`` 0 the
    chain would complete on the next read.
    """
    assert state in NODE_STATES
    token = _token(client)
    resp = client.post("/baremetal/v1/nodes", headers=_headers(token), json={
        "name": name, "driver": "ipmi", "memory_mb": 8192, "cpus": 4,
        "local_gb": 100, "cpu_arch": "x86_64",
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)
    node_id = resp.get_json()["id"]
    # A PXE-enabled port lets a later deploy succeed.
    mac = ":".join(["02"] + [node_id.replace("-", "")[i:i + 2] for i in range(0, 10, 2)])
    resp = client.post("/baremetal/v1/ports", headers=_headers(token), json={
        "node_id": node_id, "address": mac,
    })
    assert resp.status_code == 201, resp.get_data(as_text=True)
    resp = client.patch(f"/baremetal/v1/nodes/{name}", headers=_headers(token), json=[
        {"op": "add", "path": "/resource_class", "value": resource_class},
    ])
    assert resp.status_code == 200, resp.get_data(as_text=True)
    if state == "enroll":
        return node_id
    _provision(client, name, "manage")
    _settle(client)
    if state == "manageable":
        return node_id
    _provision(client, name, "provide")
    _settle(client)
    node = _node(client, node_id)
    assert node.provision_state == "available"
    if state == "available":
        return node_id
    if state == "active":
        _provision(client, name, "active")
        _settle(client)
        assert node.provision_state == "active"
    elif state == "maintenance":
        resp = client.put(f"/baremetal/v1/nodes/{name}/maintenance",
                          headers=_headers(token), json={"reason": "test"})
        assert resp.status_code == 202
    elif state == "instance_uuid":
        node.instance_uuid = "11111111-2222-3333-4444-555555555555"
    elif state == "last_error":
        node.last_error = "previous failure"
    else:  # deploying / cleaning
        node.provision_state = state
    return node_id


def _plain(value):
    return asdict(value) if is_dataclass(value) and not isinstance(value, type) else value


def snapshot(sim, client):
    """Deep copy of all state that server creation may touch."""
    limits = client.get("/compute/v2.1/limits", headers=_headers(_token(client)))
    assert limits.status_code == 200
    return {
        "nodes": {n.id: n.to_dict() for n in sim.store.baremetal_nodes.values()},
        "pending": copy.deepcopy({k: _plain(v) for k, v in sim.store.pending.items()}),
        "instances": copy.deepcopy({k: _plain(v) for k, v in sim.store.instances.items()}),
        "allocations": {
            pid: dict(view.allocations) for pid, view in sim.placement.snapshot().items()
        },
        "limits": limits.get_json()["limits"]["absolute"],
    }


def create_server(client, flavor, image_id, name="my-server"):
    return client.post("/compute/v2.1/servers", headers=_headers(_token(client)), json={
        "server": {"name": name, "flavorRef": flavor, "imageRef": image_id}
    })


def _assert_no_valid_host(client, flavor, image_id):
    sim = _sim(client)
    before = snapshot(sim, client)
    resp = create_server(client, flavor, image_id)
    assert resp.status_code == 500, (resp.status_code, resp.get_json())
    assert resp.get_json() == NO_VALID_HOST_BODY
    assert snapshot(sim, client) == before


# ---------------------------------------------------------------------------
# S0: stock flavor, no nodes
# ---------------------------------------------------------------------------


def test_s0_stock_m1_small_no_nodes_fails_with_no_valid_host(client, auth_token):
    image_id = make_image(client)
    _assert_no_valid_host(client, "m1.small", image_id)


# ---------------------------------------------------------------------------
# S1: baremetal flavor, no nodes
# ---------------------------------------------------------------------------


def test_s1_baremetal_flavor_no_nodes(client, auth_token):
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    _assert_no_valid_host(client, flavor, image_id)


# ---------------------------------------------------------------------------
# S2 to S8: a single node that must not be selected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario,state", [
    ("S2", "enroll"),
    ("S3", "manageable"),
    ("S4", "active"),
    ("S5", "maintenance"),
    ("S6", "instance_uuid"),
    ("S7", "last_error"),
    ("S8-deploying", "deploying"),
    ("S8-cleaning", "cleaning"),
])
def test_single_unschedulable_node(client, auth_token, scenario, state):
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    make_node(client, "node-1", state)
    _assert_no_valid_host(client, flavor, image_id)


# ---------------------------------------------------------------------------
# S9: pool of non-available nodes plus exactly one available node
# ---------------------------------------------------------------------------

_BAD_STATES = [s for s in NODE_STATES if s != "available"]


@settings(
    max_examples=15, deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    bad_states=st.lists(st.sampled_from(_BAD_STATES), max_size=5),
    position=st.integers(min_value=0, max_value=5),
)
def test_s9_only_available_node_is_selected(bad_states, position):
    """**Validates: Requirements 1.12, 1.13, 2.12, 2.13, 2.14**"""
    with _new_client() as client:
        _login(client)
        flavor = make_baremetal_flavor(client, "bm-small")
        image_id = make_image(client)
        states = list(bad_states)
        states.insert(min(position, len(states)), "available")
        ids = [make_node(client, f"node-{i}", s) for i, s in enumerate(states)]
        available_id = ids[states.index("available")]
        sim = _sim(client)
        before = snapshot(sim, client)

        resp = create_server(client, flavor, image_id)
        assert resp.status_code == 202, (resp.status_code, resp.get_json())
        server = resp.get_json()["server"]
        assert sim.store.instances[server["id"]].node_id == available_id
        assert _node(client, available_id).instance_uuid == server["id"]

        after = snapshot(sim, client)
        for node_id in ids:
            if node_id != available_id:
                assert after["nodes"][node_id] == before["nodes"][node_id]
                assert after["allocations"][node_id] == before["allocations"][node_id]


# ---------------------------------------------------------------------------
# S10: one available node
# ---------------------------------------------------------------------------


def test_s10_single_available_node(client, auth_token):
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    node_id = make_node(client, "node-1", "available")
    sim = _sim(client)

    resp = create_server(client, flavor, image_id)
    assert resp.status_code == 202, (resp.status_code, resp.get_json())
    server_id = resp.get_json()["server"]["id"]
    node = _node(client, node_id)
    assert node.instance_uuid == server_id
    # With time_scale 0 the chain is applied lazily on the next node read, so
    # the stored state still reads "available" here; the deploy chain
    # (deploying -> active) is pending and the node targets "active".
    pending = sim.store.pending[node_id]
    assert [s.to_state for s in pending.steps] == ["deploying", "active"]
    assert node.target_provision_state == "active"

    _settle(client)
    assert node.provision_state == "active"
    assert node.instance_uuid == server_id


def test_s10c_available_node_without_resource_class(client, auth_token):
    """A node created without ``--resource-class`` still gets inventory.

    Placement must key the provider's inventory on the flavor's effective
    class (``CUSTOM_BAREMETAL``), not on the node's raw (missing) class.
    """
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    node_id = make_node(client, "node-1", "available", resource_class=None)

    resp = create_server(client, flavor, image_id)
    assert resp.status_code == 202, (resp.status_code, resp.get_json())
    assert _node(client, node_id).instance_uuid == resp.get_json()["server"]["id"]


def test_s10b_available_node_with_ironic_style_resource_class(client, auth_token):
    """Ironic nodes carry ``baremetal``; the flavor spec is ``CUSTOM_BAREMETAL``.

    Real Ironic maps node class ``baremetal`` to Placement class
    ``CUSTOM_BAREMETAL``, so an available node must be selected.
    """
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    node_id = make_node(client, "node-1", "available", resource_class="baremetal")

    resp = create_server(client, flavor, image_id)
    assert resp.status_code == 202, (resp.status_code, resp.get_json())
    assert _node(client, node_id).instance_uuid == resp.get_json()["server"]["id"]
