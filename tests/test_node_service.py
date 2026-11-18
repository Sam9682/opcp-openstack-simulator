"""Unit tests for NodeService (server-creation-rules task 4.6)."""

from types import SimpleNamespace

import pytest

from openstack_simulator.exceptions import (
    BadRequest,
    InvalidState,
    NodeLocked,
    NodeNotProvided,
    NotAuthorized,
)
from openstack_simulator.managers.node_service import NodeService
from openstack_simulator.managers.placement import PlacementService
from openstack_simulator.models import BaremetalNode
from openstack_simulator.sim_config import load_sim_config
from openstack_simulator.store import ResourceStore


def _ctx(admin=True, project="p1", now=100.0):
    return SimpleNamespace(
        project_id=project, is_admin=admin, now=now, microversion=(2, 78)
    )


def _make(state="enroll", **kw):
    store = ResourceStore()
    node = BaremetalNode(
        id="n-1",
        name="node1",
        driver="ipmi",
        power_state="power off",
        provision_state=state,
        memory_mb=1024,
        cpus=2,
        local_gb=100,
        cpu_arch="x86_64",
        **kw,
    )
    store.baremetal_nodes["node1"] = node
    placement = PlacementService()
    svc = NodeService(store, load_sim_config(None, {"time_scale": 1.0}), placement)
    return svc, store, node, placement


def test_provision_is_async_and_locks():
    svc, store, node, _ = _make("manageable")
    svc.provision(_ctx(), "node1", "provide")
    assert node.provision_state == "manageable"
    assert node.target_provision_state == "available"
    assert "n-1" in store.pending
    with pytest.raises(NodeLocked):
        svc.provision(_ctx(), "node1", "clean")
    svc.sync(100.0)
    assert node.provision_state == "cleaning"
    svc.sync(1000.0)
    assert node.provision_state == "available"
    assert node.target_provision_state is None


def test_provision_errors():
    svc, _, node, _ = _make("available")
    with pytest.raises(NotAuthorized):
        svc.provision(_ctx(admin=False), "node1", "provide")
    with pytest.raises(NodeNotProvided):
        svc.provision(_ctx(), "node1", "provide")
    node.maintenance = True
    with pytest.raises(InvalidState):
        svc.provision(_ctx(), "node1", "clean")
    node.provision_state = "deploy failed"
    svc.provision(_ctx(), "node1", "clean")


def test_deploy_lessee_mismatch():
    svc, _, _, _ = _make("available", lessee="other")
    with pytest.raises(NotAuthorized):
        svc.provision(_ctx(project="p1"), "node1", "active")


def test_owner_and_lessee_rules():
    svc, store, node, _ = _make("available")
    with pytest.raises(NotAuthorized):
        svc.set_owner(_ctx(admin=False), "node1", "p1")
    svc.set_owner(_ctx(), "node1", "p1")
    assert node.owner == "p1" and node.provision_state == "available"
    assert "n-1" not in store.pending
    with pytest.raises(BadRequest):
        svc.set_lessee(_ctx(), "node1", "bad id!")
    node.provision_state = "active"
    with pytest.raises(InvalidState):
        svc.set_owner(_ctx(), "node1", "p2")
    node.instance_uuid = "s1"
    store.instances["s1"] = SimpleNamespace(project_id="p1")
    with pytest.raises(InvalidState):
        svc.set_lessee(_ctx(), "node1", "p2")
    svc.set_lessee(_ctx(), "node1", "p1")
    assert node.lessee == "p1"


def test_traits_sync_to_placement_and_active_untouched():
    svc, _, node, placement = _make("active")
    svc.add_trait("node1", "custom_gpu")
    svc.add_trait("node1", "CUSTOM_SSD")
    assert node.traits == ["CUSTOM_GPU", "CUSTOM_SSD"]
    assert placement.snapshot()["n-1"].traits == frozenset(node.traits)
    svc.remove_trait("node1", "custom_gpu")
    assert node.traits == ["CUSTOM_SSD"]
    assert node.provision_state == "active"


def test_visible_nodes():
    svc, _, node, _ = _make("available", owner="p1")
    assert svc.visible_nodes(_ctx(admin=False, project="p1")) == [node]
    assert svc.visible_nodes(_ctx(admin=False, project="p2")) == []
    assert svc.visible_nodes(_ctx(admin=True, project="p2")) == [node]
    node.owner, node.lessee = None, "p2"
    assert svc.visible_nodes(_ctx(admin=False, project="p2")) == [node]
