"""Baremetal API extensions: verbs, node fields, maintenance, traits, locking."""

import pytest

from openstack_simulator.api.app import create_app

BM = "/baremetal/v1"


@pytest.fixture
def client():
    app = create_app({"time_scale": 1.0})
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def h(client):
    resp = client.post(
        "/identity/v3/auth/tokens",
        json={"auth": {"identity": {"methods": ["password"], "password": {"user": {
            "name": "admin", "domain": {"name": "Default"}, "password": "x"}}}}},
    )
    return {"X-Auth-Token": resp.headers["X-Subject-Token"]}


def _node(client, h, name="n1"):
    r = client.post(f"{BM}/nodes", headers=h, json={"name": name, "driver": "ipmi"})
    assert r.status_code == 201
    return r.get_json()["uuid"] if "uuid" in r.get_json() else name


def test_manage_is_async_and_second_verb_is_locked(client, h):
    _node(client, h)
    r = client.put(f"{BM}/nodes/n1/states/provision", headers=h, json={"target": "manage"})
    assert r.status_code == 202
    assert client.get(f"{BM}/nodes/n1", headers=h).get_json()["provision_state"] == "enroll"
    r = client.put(f"{BM}/nodes/n1/states/provision", headers=h, json={"target": "manage"})
    assert r.status_code == 409
    assert "error_message" in r.get_json()


def test_unknown_target_400(client, h):
    _node(client, h)
    r = client.put(f"{BM}/nodes/n1/states/provision", headers=h, json={"target": "bogus"})
    assert r.status_code == 400


def test_patch_fields_and_raid_validation(client, h):
    _node(client, h)
    ops = [
        {"op": "replace", "path": "/owner", "value": "proj1"},
        {"op": "replace", "path": "/resource_class", "value": "gold"},
        {"op": "replace", "path": "/protected", "value": True},
    ]
    r = client.patch(f"{BM}/nodes/n1", headers=h, json=ops)
    assert r.status_code == 200
    body = r.get_json()
    assert (body["owner"], body["resource_class"], body["protected"]) == ("proj1", "gold", True)

    bad = [{"op": "add", "path": "/target_raid_config", "value": {
        "logical_disks": [{"size_gb": 10, "raid_level": "0", "is_root_volume": True}]}}]
    assert client.patch(f"{BM}/nodes/n1", headers=h, json=bad).status_code == 400
    good = [{"op": "add", "path": "/target_raid_config", "value": {
        "logical_disks": [{"size_gb": 10, "raid_level": "1", "is_root_volume": True}]}}]
    assert client.patch(f"{BM}/nodes/n1", headers=h, json=good).status_code == 200


def test_maintenance_and_traits(client, h):
    _node(client, h)
    assert client.put(f"{BM}/nodes/n1/maintenance", headers=h, json={"reason": "r"}).status_code == 202
    body = client.get(f"{BM}/nodes/n1", headers=h).get_json()
    assert body["maintenance"] is True and body["maintenance_reason"] == "r"
    assert client.delete(f"{BM}/nodes/n1/maintenance", headers=h).status_code == 202
    assert client.get(f"{BM}/nodes/n1", headers=h).get_json()["maintenance"] is False

    assert client.put(f"{BM}/nodes/n1/traits/custom_x", headers=h).status_code == 204
    assert client.put(f"{BM}/nodes/n1/traits/bad-trait", headers=h).status_code == 400
    assert client.get(f"{BM}/nodes/n1", headers=h).get_json()["traits"] == ["CUSTOM_X"]
    assert client.delete(f"{BM}/nodes/n1/traits/CUSTOM_X", headers=h).status_code == 204
    assert client.get(f"{BM}/nodes/n1", headers=h).get_json()["traits"] == []


def test_deploy_with_other_lessee_is_403(client, h):
    _node(client, h)
    client.patch(f"{BM}/nodes/n1", headers=h,
                 json=[{"op": "replace", "path": "/lessee", "value": "other"}])
    r = client.put(f"{BM}/nodes/n1/states/provision", headers=h, json={"target": "active"})
    assert r.status_code == 403
