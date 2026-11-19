"""Bug condition exploration: baremetal node responses must carry ``uuid``.

Replays the ``openstack baremetal node create/list/show`` CLI flows against the
Flask test client. On UNFIXED code these tests are expected to FAIL because
``BaremetalNode.to_dict()`` only exposes ``id``.

**Validates: Requirements 1.7, 1.8, 1.9** (expected behavior 2.7, 2.8, 2.9)
"""

import uuid as uuid_lib

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from openstack_simulator.api.app import create_app
from openstack_simulator.models import BaremetalNode

IRONIC_VERSION = "1.58"
CLI_LIST_COLUMNS = ("uuid", "name", "instance_uuid", "power_state",
                    "provision_state", "maintenance")

node_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=30
).filter(lambda s: s[0].isalnum())
drivers = st.sampled_from(["ipmi", "fake", "redfish", "idrac"])
memory_mb = st.integers(min_value=0, max_value=1_048_576)
cpus = st.integers(min_value=0, max_value=256)
local_gb = st.integers(min_value=0, max_value=10_000)
cpu_archs = st.sampled_from(["x86_64", "aarch64"])


def _new_client():
    app = create_app({"time_scale": 0})
    app.config["TESTING"] = True
    return app.test_client()


def _cli_headers(client):
    resp = client.post("/identity/v3/auth/tokens", json={
        "auth": {"identity": {
            "methods": ["application_credential"],
            "application_credential": {
                "id": "simulator-app-credential",
                "secret": "simulator-secret",
            },
        }}
    })
    assert resp.status_code == 201
    return {
        "X-Auth-Token": resp.headers["X-Subject-Token"],
        "X-OpenStack-Ironic-API-Version": IRONIC_VERSION,
        "Content-Type": "application/json",
    }


def _assert_uuid4(value):
    assert isinstance(value, str) and value, f"uuid missing or empty: {value!r}"
    parsed = uuid_lib.UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


def test_cli_node_create_minimal_has_uuid():
    """`openstack baremetal node create --driver ipmi --name my-node`."""
    client = _new_client()
    headers = _cli_headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"driver": "ipmi", "name": "my-node"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert "uuid" in body, f"create response has no 'uuid' key: {sorted(body)}"
    _assert_uuid4(body["uuid"])
    assert body["uuid"] == body["id"]


def test_to_dict_uuid_equals_id():
    node = BaremetalNode(
        id=str(uuid_lib.uuid4()), name="n", driver="ipmi",
        power_state="power off", provision_state="enroll",
        memory_mb=0, cpus=0, local_gb=0, cpu_arch="x86_64",
    )
    d = node.to_dict()
    assert "uuid" in d, f"to_dict has no 'uuid' key: {sorted(d)}"
    assert d["uuid"] == d["id"]


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(name=node_names, driver=drivers, mem=memory_mb, n_cpus=cpus,
       disk=local_gb, arch=cpu_archs)
def test_uuid_consistent_across_create_list_detail_show(
        name, driver, mem, n_cpus, disk, arch):
    client = _new_client()
    headers = _cli_headers(client)

    resp = client.post("/baremetal/v1/nodes", headers=headers, json={
        "name": name, "driver": driver, "memory_mb": mem, "cpus": n_cpus,
        "local_gb": disk, "cpu_arch": arch,
    })
    assert resp.status_code == 201
    created = resp.get_json()
    assert created.get("uuid"), f"create: missing uuid, keys={sorted(created)}"
    _assert_uuid4(created["uuid"])
    assert created["uuid"] == created["id"]

    for path in ("/baremetal/v1/nodes", "/baremetal/v1/nodes/detail"):
        resp = client.get(path, headers=headers)
        assert resp.status_code == 200
        nodes = resp.get_json()["nodes"]
        assert len(nodes) == 1
        item = nodes[0]
        for col in CLI_LIST_COLUMNS:
            assert col in item, f"{path}: column {col!r} missing in {sorted(item)}"
        assert item["uuid"], f"{path}: empty uuid"
        assert item["uuid"] == created["uuid"]

    for ident in (name, created["id"]):
        resp = client.get(f"/baremetal/v1/nodes/{ident}", headers=headers)
        assert resp.status_code == 200
        shown = resp.get_json()
        assert shown.get("uuid"), f"show {ident}: missing uuid"
        assert shown["uuid"] == created["uuid"]


# ---------------------------------------------------------------------------
# Task 3: explicit ``uuid`` on POST /baremetal/v1/nodes (Requirement 1.10).
# On UNFIXED code the supplied value is ignored and a random UUID is generated.
# **Validates: Requirements 1.10** (expected behavior 2.10)
# ---------------------------------------------------------------------------

from openstack_simulator.exceptions import DuplicateResourceError
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.baremetal import BaremetalManager
from openstack_simulator.store import ResourceStore

FIXED_UUID = "11111111-2222-4333-8444-555555555555"


def _node_count(client):
    return client.application.config["SIMULATOR"].store.count_active(
        "baremetal_nodes")


def _assert_error_envelope(resp, code):
    assert resp.status_code == code, resp.get_data(as_text=True)
    body = resp.get_json()
    assert set(body) == {"error"}, body
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["error"]["code"] == code


def _new_manager():
    return BaremetalManager(
        store=ResourceStore(), limiter=ResourceLimiter({"baremetal_nodes": 100}))


def _is_uuid_string(s):
    try:
        uuid_lib.UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


malformed_strings = st.one_of(
    st.just("not-a-uuid"),
    st.just(""),
    st.text(max_size=40).filter(lambda s: not _is_uuid_string(s)),
)
non_string_values = st.one_of(
    st.integers(), st.booleans(), st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)


def test_explicit_uuid_example_create_and_read_back():
    client = _new_client()
    headers = _cli_headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"name": "n", "driver": "ipmi", "uuid": FIXED_UUID})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] == FIXED_UUID
    assert body.get("uuid") == FIXED_UUID


def test_explicit_uuid_uppercase_returned_canonical_lowercase():
    client = _new_client()
    headers = _cli_headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"name": "n", "driver": "ipmi",
                             "uuid": FIXED_UUID.upper()})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["id"] == FIXED_UUID
    assert body.get("uuid") == FIXED_UUID


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(supplied=st.uuids(), name=node_names, driver=drivers,
       upper=st.booleans())
def test_explicit_valid_uuid_used_and_consistent(supplied, name, driver, upper):
    client = _new_client()
    headers = _cli_headers(client)
    canonical = str(supplied)
    sent = canonical.upper() if upper else canonical

    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"name": name, "driver": driver, "uuid": sent})
    assert resp.status_code == 201, resp.get_data(as_text=True)
    created = resp.get_json()
    assert created["id"] == canonical, "supplied uuid ignored"
    assert created.get("uuid") == canonical

    for path in ("/baremetal/v1/nodes", "/baremetal/v1/nodes/detail"):
        nodes = client.get(path, headers=headers).get_json()["nodes"]
        assert [n.get("uuid") for n in nodes] == [canonical]
        assert [n["id"] for n in nodes] == [canonical]
    for ident in (name, canonical):
        shown = client.get(f"/baremetal/v1/nodes/{ident}", headers=headers)
        assert shown.status_code == 200
        assert shown.get_json()["id"] == canonical
        assert shown.get_json().get("uuid") == canonical


@pytest.mark.parametrize("bad", ["not-a-uuid", "", 123, True, [], {}])
def test_malformed_uuid_examples_rejected_400(bad):
    client = _new_client()
    headers = _cli_headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"name": "n", "driver": "ipmi", "uuid": bad})
    _assert_error_envelope(resp, 400)
    assert _node_count(client) == 0


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(bad=st.one_of(malformed_strings, non_string_values), name=node_names,
       driver=drivers)
def test_malformed_uuid_rejected_with_no_node_created(bad, name, driver):
    client = _new_client()
    headers = _cli_headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=headers,
                       json={"name": name, "driver": driver, "uuid": bad})
    _assert_error_envelope(resp, 400)
    assert _node_count(client) == 0


@settings(max_examples=25, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(supplied=st.uuids(), first=node_names, second=node_names)
def test_duplicate_uuid_different_name_returns_409_store_unchanged(
        supplied, first, second):
    if first == second:
        second = second + "-b"
    client = _new_client()
    headers = _cli_headers(client)
    canonical = str(supplied)
    r1 = client.post("/baremetal/v1/nodes", headers=headers,
                     json={"name": first, "driver": "ipmi", "uuid": canonical})
    assert r1.status_code == 201
    before = client.get("/baremetal/v1/nodes/detail",
                        headers=headers).get_json()

    r2 = client.post("/baremetal/v1/nodes", headers=headers,
                     json={"name": second, "driver": "ipmi", "uuid": canonical})
    assert r2.status_code == 409, r2.get_data(as_text=True)
    assert _node_count(client) == 1
    after = client.get("/baremetal/v1/nodes/detail", headers=headers).get_json()
    assert after == before


# --- Manager level ---------------------------------------------------------

@settings(max_examples=25, deadline=None)
@given(supplied=st.uuids())
def test_manager_create_node_uses_supplied_uuid(supplied):
    mgr = _new_manager()
    node = mgr.create_node("n", "ipmi", uuid=str(supplied))
    assert node.id == str(supplied)


@settings(max_examples=25, deadline=None)
@given(supplied=st.uuids())
def test_manager_create_node_duplicate_uuid_raises(supplied):
    mgr = _new_manager()
    mgr.create_node("a", "ipmi", uuid=str(supplied))
    with pytest.raises(DuplicateResourceError):
        mgr.create_node("b", "ipmi", uuid=str(supplied))
    assert mgr.store.count_active("baremetal_nodes") == 1


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "1234"])
def test_manager_create_node_malformed_uuid_raises_value_error(bad):
    mgr = _new_manager()
    with pytest.raises(ValueError):
        mgr.create_node("n", "ipmi", uuid=bad)
    assert mgr.store.count_active("baremetal_nodes") == 0


def test_manager_uuid_of_deleted_node_can_be_reused():
    """Decision (task 8.5): duplicates are checked against active nodes only,
    so a UUID may be reused after the node is deleted."""
    mgr = _new_manager()
    mgr.create_node("a", "ipmi", uuid=FIXED_UUID)
    mgr.delete_node("a")
    node = mgr.create_node("b", "ipmi", uuid=FIXED_UUID.upper())
    assert node.id == FIXED_UUID
    with pytest.raises(DuplicateResourceError):
        mgr.create_node("c", "ipmi", uuid=FIXED_UUID)
