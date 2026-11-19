"""Preservation tests for server create scheduling (observation-first).

Recorded on the UNFIXED code. They pin the behavior that must not change when
server create is made to schedule only onto ``available`` nodes:

- (a) a create with an ``available`` schedulable node picks the node
  deterministically from the seed and the server name, sets ``instance_uuid``,
  and goes ``deploying`` then ``active`` after ``/_sim/settle``;
- (b) validation and lookup failures keep their status and message and leave
  nodes, allocations, pending transitions and quota untouched;
- (c) server delete, an injected deploy failure and a lost Placement claim
  free the allocation and quota as before;
- (d) the legacy path (flavor without a resource class) returns 202 and creates
  a virtual server. This is the current legacy behavior, not a requirement.

Observations that are NOT asserted, because they look like existing defects
rather than behavior to keep:

- ``ServerCreationService._node_of`` looks the node up by uuid while the store
  is keyed by node name, so deleting a server bound to a node leaves the node
  ``active`` with its ``instance_uuid`` and keeps the Placement allocation.
  Only the server (status ``DELETED``) and the quota usage are released.

Requirements: 3.10, 3.11, 3.12, 3.13
"""

import uuid

from hypothesis import HealthCheck, given, settings, strategies as st

from openstack_simulator.api.app import create_app
from openstack_simulator.managers.scheduler import pick

from .test_server_create_no_available_node import (
    NO_VALID_HOST_BODY,
    _headers,
    _login,
    _node,
    _settle,
    _sim,
    _token,
    create_server,
    make_baremetal_flavor,
    make_image,
    make_node,
    snapshot,
)

PBT = settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=20)
seeds = st.integers(min_value=0, max_value=10_000)
bad_states = st.lists(st.sampled_from(["enroll", "manageable", "active", "maintenance"]), max_size=2)


def _client(seed=42, **config):
    app = create_app({"time_scale": 0, "seed": seed, **config})
    app.config["TESTING"] = True
    client = app.test_client()
    client.__enter__()
    _login(client)
    return client


def _world(seed, n_available, extra_states=(), **config):
    """Fresh simulator with a flavor, an image and a pool of nodes."""
    client = _client(seed, **config)
    flavor = make_baremetal_flavor(client, "bm-small")
    image_id = make_image(client)
    ids = [make_node(client, f"avail-{i}", "available") for i in range(n_available)]
    for i, state in enumerate(extra_states):
        make_node(client, f"other-{i}", state)
    return client, flavor, image_id, ids


def _post(client, body):
    return client.post("/compute/v2.1/servers", headers=_headers(_token(client)),
                       json={"server": body})


def _usage(client):
    resp = client.get("/compute/v2.1/limits", headers=_headers(_token(client)))
    return resp.get_json()["limits"]["absolute"]["totalInstancesUsed"]


def _server_view(client, server_id):
    resp = client.get(f"/compute/v2.1/servers/{server_id}", headers=_headers(_token(client)))
    assert resp.status_code == 200
    return resp.get_json()["server"]


def _allocations(client):
    return {pid: dict(v.allocations) for pid, v in _sim(client).placement.snapshot().items()}


# ---------------------------------------------------------------------------
# (a) successful create
# ---------------------------------------------------------------------------


@PBT
@given(seed=seeds, name=names, n=st.integers(1, 4), extra=bad_states)
def test_create_picks_node_deterministically_and_deploys(seed, name, n, extra):
    """**Validates: Requirements 3.10**"""
    ranks = []
    for _ in range(2):  # two fresh simulators with the same seed and name
        client, flavor, image_id, ids = _world(seed, n, extra)
        ordered = sorted(ids)
        expected = pick(ordered, seed, name)[0]

        resp = create_server(client, flavor, image_id, name=name)
        assert resp.status_code == 202, resp.get_json()
        server_id = resp.get_json()["server"]["id"]
        node = _node(client, expected)
        assert node.instance_uuid == server_id
        assert node.target_provision_state == "active"
        assert [s.to_state for s in _sim(client).store.pending[expected].steps] == [
            "deploying", "active",
        ]
        assert _allocations(client)[expected] == {server_id: "CUSTOM_BAREMETAL"}
        for other in ids:
            if other != expected:
                assert _node(client, other).instance_uuid is None

        _settle(client)
        assert node.provision_state == "active"
        assert node.instance_uuid == server_id
        assert _server_view(client, server_id)["status"] == "ACTIVE"
        ranks.append(ordered.index(expected))
    assert ranks[0] == ranks[1]


# ---------------------------------------------------------------------------
# (b) failures before scheduling
# ---------------------------------------------------------------------------

_B64 = "aGVsbG8="


def _failure_cases(flavor, image_id):
    ghost = str(uuid.uuid4())
    base = {"flavorRef": flavor, "imageRef": image_id}
    return {
        "bad-networks": (dict(base, networks="bogus"), 400,
                         "Invalid input for field/attribute networks."),
        "missing-image": ({"flavorRef": flavor}, 400,
                          "Invalid input for field/attribute imageRef."),
        "bad-user-data": (dict(base, user_data="not base64!"), 400,
                          "Invalid input for field/attribute user_data."),
        "unknown-image": (dict(base, imageRef=ghost), 400, f"Image {ghost} could not be found."),
        "unknown-keypair": (dict(base, key_name="nokey"), 400, "Keypair nokey not found for user"),
        "unknown-security-group": (dict(base, security_groups=[{"name": "nosg"}]), 400,
                                   "Security group nosg not found for project"),
        "unknown-network": (dict(base, networks=[{"uuid": "nonet"}]), 404,
                            "Network nonet could not be found."),
        "invalid-az": (dict(base, availability_zone=f"nova::{ghost}"), 400,
                       f"Invalid availability zone: [nova::{ghost}]"),
        "strict-capacity": (dict(base, flavorRef="bm-huge"), 400,
                            "Flavor's resources exceed the capacity of the available bare metal nodes."),
    }


@PBT
@given(case=st.sampled_from(sorted(_failure_cases("f", "i"))), name=names, seed=seeds,
       n=st.integers(0, 3), extra=bad_states)
def test_validation_failures_keep_status_and_leave_scheduler_untouched(case, name, seed, n, extra):
    """**Validates: Requirements 3.11**"""
    client, flavor, image_id, _ids = _world(seed, n, extra)
    resp = client.post("/compute/v2.1/flavors", headers=_headers(_token(client)), json={
        "flavor": {"name": "bm-huge", "id": "bm-huge", "ram": 10**6, "vcpus": 1, "disk": 20,
                   "extra_specs": {"resources:CUSTOM_BAREMETAL": "1"}},
    })
    assert resp.status_code == 200
    body, status, message = _failure_cases(flavor, image_id)[case]
    if case == "strict-capacity" and n == 0 and not extra:
        return  # empty pool: the capacity check does not apply
    sim = _sim(client)
    before = snapshot(sim, client)

    resp = _post(client, dict(body, name=name))
    assert resp.status_code == status, resp.get_json()
    (envelope,) = resp.get_json().values()
    assert message in envelope["message"]
    assert snapshot(sim, client) == before
    assert not sim.store.instances


def test_empty_server_name_is_rejected_before_scheduling():
    client, flavor, image_id, _ = _world(42, 1)
    sim = _sim(client)
    before = snapshot(sim, client)
    resp = _post(client, {"name": "", "flavorRef": flavor, "imageRef": image_id})
    assert resp.status_code == 400
    assert resp.get_json() == {"badRequest": {"message": "Server name is required", "code": 400}}
    assert snapshot(sim, client) == before


@PBT
@given(seed=seeds, name=names, n=st.integers(1, 3))
def test_quota_exceeded_keeps_message_and_changes_nothing(seed, name, n):
    """**Validates: Requirements 3.11**"""
    client, flavor, image_id, _ids = _world(seed, n, max_instances=1)
    assert _post(client, {"name": name, "flavorRef": flavor, "imageRef": image_id}).status_code == 202
    _settle(client)  # reads apply pending transitions; start from a settled state
    sim = _sim(client)
    before = snapshot(sim, client)

    resp = _post(client, {"name": name + "-2", "flavorRef": flavor, "imageRef": image_id})
    assert resp.status_code == 403
    assert resp.get_json() == {"forbidden": {
        "code": 403,
        "message": "Quota exceeded for instances: Requested 1, but already used 1 of 1.",
    }}
    assert snapshot(sim, client) == before


# ---------------------------------------------------------------------------
# (c) delete, deploy failure, lost claim
# ---------------------------------------------------------------------------


@PBT
@given(seed=seeds, name=names, n=st.integers(1, 3))
def test_delete_releases_server_and_quota(seed, name, n):
    """**Validates: Requirements 3.12**"""
    client, flavor, image_id, _ids = _world(seed, n)
    server_id = create_server(client, flavor, image_id, name=name).get_json()["server"]["id"]
    _settle(client)
    assert _usage(client) == 1

    resp = client.delete(f"/compute/v2.1/servers/{server_id}", headers=_headers(_token(client)))
    assert resp.status_code == 204
    assert _sim(client).store.instances[server_id].status == "DELETED"
    assert _usage(client) == 0
    # A repeated delete stays a 204.
    resp = client.delete(f"/compute/v2.1/servers/{server_id}", headers=_headers(_token(client)))
    assert resp.status_code == 204
    assert _usage(client) == 0


@PBT
@given(seed=seeds, name=names, n=st.integers(1, 3), message=st.sampled_from(["boom", "disk failure"]))
def test_injected_deploy_failure_errors_server_and_frees_allocation(seed, name, n, message):
    """**Validates: Requirements 3.12**"""
    client, flavor, image_id, ids = _world(seed, n)
    for node_id in ids:
        resp = client.post(f"/_sim/nodes/{node_id}/fail-next", headers=_headers(_token(client)),
                           json={"op": "deploy", "last_error": message})
        assert resp.status_code == 200
    expected = pick(sorted(ids), seed, name)[0]
    server_id = create_server(client, flavor, image_id, name=name).get_json()["server"]["id"]
    assert _allocations(client)[expected] == {server_id: "CUSTOM_BAREMETAL"}

    _settle(client)
    view = _server_view(client, server_id)
    assert view["status"] == "ERROR"
    assert view["fault"]["message"] == f"Deploy failed: {message}"
    node = _node(client, expected)
    assert node.provision_state == "deploy failed"
    assert node.last_error == message
    assert all(not alloc for alloc in _allocations(client).values())
    # The failed server keeps its quota until it is deleted.
    assert _usage(client) == 1
    resp = client.delete(f"/compute/v2.1/servers/{server_id}", headers=_headers(_token(client)))
    assert resp.status_code == 204
    assert _usage(client) == 0


@PBT
@given(seed=seeds, name=names, n=st.integers(2, 4))
def test_lost_claim_falls_back_to_next_candidate_and_leaves_first_untouched(seed, name, n):
    """**Validates: Requirements 3.12**"""
    client, flavor, image_id, ids = _world(seed, n)
    sim = _sim(client)
    order = pick(sorted(ids), seed, name)
    real_claim = sim.placement.claim

    def lose_first(provider_id, consumer_id, rc):
        if provider_id == order[0]:
            return False  # another request won the race for this node
        return real_claim(provider_id, consumer_id, rc)

    sim.placement.claim = lose_first
    resp = create_server(client, flavor, image_id, name=name)
    assert resp.status_code == 202, resp.get_json()
    server_id = resp.get_json()["server"]["id"]
    assert _node(client, order[1]).instance_uuid == server_id
    assert _node(client, order[0]).instance_uuid is None
    assert order[0] not in sim.store.pending
    assert _allocations(client)[order[0]] == {}


@PBT
@given(seed=seeds, name=names)
def test_lost_claim_on_only_node_is_no_valid_host_and_changes_nothing(seed, name):
    """**Validates: Requirements 3.12**"""
    client, flavor, image_id, _ids = _world(seed, 1)
    sim = _sim(client)
    sim.placement.claim = lambda provider_id, consumer_id, rc: False
    before = snapshot(sim, client)
    resp = create_server(client, flavor, image_id, name=name)
    assert resp.status_code == 500
    assert resp.get_json() == NO_VALID_HOST_BODY
    assert snapshot(sim, client) == before


# ---------------------------------------------------------------------------
# (d) legacy path (current behavior, recorded)
# ---------------------------------------------------------------------------


@PBT
@given(seed=seeds, name=names, flavor=st.sampled_from(["m1.small", "m1.tiny"]))
def test_legacy_flavor_without_resource_class_creates_virtual_server(seed, name, flavor):
    """Current legacy behavior: stock flavors never reach the scheduler.

    **Validates: Requirements 3.13**
    """
    client = _client(seed)
    resp = _post(client, {"name": name, "flavorRef": flavor, "imageRef": "ubuntu-22.04"})
    assert resp.status_code == 202, resp.get_json()
    server_id = resp.get_json()["server"]["id"]
    server = next(s for s in _sim(client).store.instances.values() if s.id == server_id)
    assert server.node_id is None
    assert server.status == "ACTIVE"
    assert not _sim(client).store.baremetal_nodes
    assert not _sim(client).store.pending
