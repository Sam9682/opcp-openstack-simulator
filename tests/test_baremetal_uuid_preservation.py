"""Preservation: baremetal behaviour that must not change when ``uuid`` is added.

Node responses are compared ignoring the ``uuid`` key so these tests pass both
before and after the fix.

**Validates: Requirements 3.5, 3.6, 3.7, 3.8, 3.9**
"""

from openstack_simulator.credentials import credential_secret
import uuid as uuid_lib

from hypothesis import HealthCheck, given, settings, strategies as st

from openstack_simulator.api.app import create_app
from openstack_simulator.models import BaremetalNode

node_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=30
).filter(lambda s: s[0].isalnum())
drivers = st.sampled_from(["ipmi", "fake", "redfish", "idrac"])
memory_mb = st.integers(min_value=0, max_value=1_048_576)
cpus = st.integers(min_value=0, max_value=256)
local_gb = st.integers(min_value=0, max_value=10_000)
cpu_archs = st.sampled_from(["x86_64", "aarch64"])
macs = st.integers(min_value=0, max_value=2**48 - 1).map(
    lambda n: ":".join(f"{(n >> s) & 0xFF:02x}" for s in range(40, -8, -8)))

PBT = settings(max_examples=25, deadline=None,
               suppress_health_check=[HealthCheck.function_scoped_fixture])


def _new_client(**config):
    app = create_app({"time_scale": 0, **config})
    app.config["TESTING"] = True
    return app.test_client()


def _headers(client):
    resp = client.post("/identity/v3/auth/tokens", json={
        "auth": {"identity": {
            "methods": ["application_credential"],
            "application_credential": {
                "id": "simulator",
                "secret": credential_secret("simulator"),
            },
        }}
    })
    assert resp.status_code == 201
    return {
        "X-Auth-Token": resp.headers["X-Subject-Token"],
        "X-OpenStack-Ironic-API-Version": "1.58",
        "Content-Type": "application/json",
    }


def _strip(d):
    return {k: v for k, v in d.items() if k != "uuid"}


def _sim(client):
    return client.application.config["SIMULATOR"]


@PBT
@given(name=node_names, driver=drivers, mem=memory_mb, n_cpus=cpus,
       disk=local_gb, arch=cpu_archs)
def test_create_get_and_to_dict_preserved(name, driver, mem, n_cpus, disk, arch):
    client = _new_client()
    h = _headers(client)
    resp = client.post("/baremetal/v1/nodes", headers=h, json={
        "name": name, "driver": driver, "memory_mb": mem, "cpus": n_cpus,
        "local_gb": disk, "cpu_arch": arch})
    assert resp.status_code == 201
    created = resp.get_json()
    uuid_lib.UUID(created["id"])
    assert created["provision_state"] == "enroll"
    assert created["power_state"] == "power off"
    assert created["instance_uuid"] is None
    assert (created["name"], created["driver"], created["memory_mb"],
            created["cpus"], created["local_gb"], created["cpu_arch"]) == (
        name, driver, mem, n_cpus, disk, arch)

    node = _sim(client).baremetal_manager.get_node(name)
    assert _strip(created) == _strip(node.to_dict())
    assert created["id"] == node.id

    for ident in (name, created["id"]):
        shown = client.get(f"/baremetal/v1/nodes/{ident}", headers=h)
        assert shown.status_code == 200
        assert _strip(shown.get_json()) == _strip(created)
    for path in ("/baremetal/v1/nodes", "/baremetal/v1/nodes/detail"):
        nodes = client.get(path, headers=h).get_json()["nodes"]
        assert [_strip(n) for n in nodes] == [_strip(created)]


@PBT
@given(name=node_names, driver=drivers, mac=macs)
def test_sub_resources_by_name_and_id(name, driver, mac):
    client = _new_client()
    h = _headers(client)
    node = client.post("/baremetal/v1/nodes", headers=h,
                       json={"name": name, "driver": driver}).get_json()
    nid = node["id"]

    port = client.post("/baremetal/v1/ports", headers=h,
                       json={"node_id": nid, "address": mac})
    assert port.status_code == 201
    assert port.get_json()["node_id"] == nid
    assert node["instance_uuid"] is None

    for ident in (name, nid):
        v = client.get(f"/baremetal/v1/nodes/{ident}/validate", headers=h)
        assert v.status_code == 200
        assert all(i["result"] is True for i in v.get_json().values())

        ports = client.get(f"/baremetal/v1/nodes/{ident}/ports", headers=h)
        assert ports.status_code == 200
        assert [p["node_id"] for p in ports.get_json()["ports"]] == [nid]

        _sim(client).baremetal_manager.get_node(name).provision_state = "enroll"
        assert client.put(f"/baremetal/v1/nodes/{ident}/states/provision",
                          headers=h, json={"target": "manage"}
                          ).status_code == 202
        _sim(client).baremetal_manager.get_node(name).provision_state = "available"
        assert client.put(f"/baremetal/v1/nodes/{ident}/states/power",
                          headers=h, json={"target": "power on"}
                          ).status_code == 202

        assert client.put(f"/baremetal/v1/nodes/{ident}/maintenance",
                          headers=h, json={"reason": "r"}).status_code == 202
        assert client.get(f"/baremetal/v1/nodes/{ident}",
                          headers=h).get_json()["maintenance"] is True
        assert client.delete(f"/baremetal/v1/nodes/{ident}/maintenance",
                             headers=h).status_code == 202
        assert client.get(f"/baremetal/v1/nodes/{ident}",
                          headers=h).get_json()["maintenance"] is False

    for ident, trait in ((name, "CUSTOM_A"), (nid, "CUSTOM_B")):
        assert client.put(f"/baremetal/v1/nodes/{ident}/traits/{trait}",
                          headers=h).status_code == 204
    sim = _sim(client)
    assert {"CUSTOM_A", "CUSTOM_B"} <= set(sim.placement.snapshot()[nid].traits)
    assert client.delete(f"/baremetal/v1/nodes/{name}/traits/CUSTOM_A",
                         headers=h).status_code == 204
    assert client.delete(f"/baremetal/v1/nodes/{nid}/traits/CUSTOM_B",
                         headers=h).status_code == 204
    assert client.get(f"/baremetal/v1/nodes/{nid}",
                      headers=h).get_json()["traits"] == []
    # Placement provider keyed by node id.
    assert nid in sim.placement.snapshot()
    assert sim.placement.snapshot()[nid].uuid == nid


@PBT
@given(name=node_names, driver=drivers)
def test_create_validation_and_duplicate(name, driver):
    client = _new_client()
    h = _headers(client)
    assert client.post("/baremetal/v1/nodes", headers=h,
                       json={"driver": driver}).status_code == 400
    assert client.post("/baremetal/v1/nodes", headers=h,
                       json={"name": name}).status_code == 400
    assert client.post("/baremetal/v1/nodes", headers=h,
                       json={"name": name, "driver": driver}).status_code == 201
    assert client.post("/baremetal/v1/nodes", headers=h,
                       json={"name": name, "driver": driver}).status_code == 409


@PBT
@given(limit=st.integers(min_value=1, max_value=4), driver=drivers)
def test_node_limit_413(limit, driver):
    client = _new_client(max_baremetal_nodes=limit)
    h = _headers(client)
    for i in range(limit):
        r = client.post("/baremetal/v1/nodes", headers=h,
                        json={"name": f"n{i}", "driver": driver})
        assert r.status_code == 201
    r = client.post("/baremetal/v1/nodes", headers=h,
                    json={"name": "extra", "driver": driver})
    assert r.status_code == 413


@PBT
@given(name=node_names, driver=drivers, op=st.sampled_from(["deploy", "clean"]))
def test_sim_fail_next_accepts_node_id(name, driver, op):
    client = _new_client()
    h = _headers(client)
    nid = client.post("/baremetal/v1/nodes", headers=h,
                      json={"name": name, "driver": driver}).get_json()["id"]
    r = client.post(f"/_sim/nodes/{nid}/fail-next", headers=h, json={"op": op})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["node"] == nid
    assert r.get_json()["op"] == op


@PBT
@given(name=node_names, driver=drivers, mem=memory_mb, n_cpus=cpus,
       disk=local_gb, arch=cpu_archs)
def test_from_dict_without_uuid_key_loads(name, driver, mem, n_cpus, disk, arch):
    nid = str(uuid_lib.uuid4())
    persisted = {
        "id": nid, "name": name, "driver": driver,
        "power_state": "power off", "provision_state": "enroll",
        "memory_mb": mem, "cpus": n_cpus, "local_gb": disk, "cpu_arch": arch,
    }
    assert "uuid" not in persisted
    node = BaremetalNode.from_dict(persisted)
    assert node.id == nid
    assert node.name == name
    assert node.instance_uuid is None
    d = node.to_dict()
    assert d["id"] == nid
    assert BaremetalNode.from_dict(_strip(d)).to_dict() == d
