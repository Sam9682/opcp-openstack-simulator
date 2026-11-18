"""Legacy BaremetalManager delegating to NodeService (server-creation-rules 4.13)."""

import pytest

from openstack_simulator.clock import Clock
from openstack_simulator.exceptions import InvalidStateError
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.baremetal import BaremetalManager
from openstack_simulator.managers.node_service import NodeService
from openstack_simulator.managers.placement import PlacementService
from openstack_simulator.sim_config import load_sim_config
from openstack_simulator.store import ResourceStore


def _mgr(time_scale=0.0, clock=None):
    store = ResourceStore()
    cfg = load_sim_config(None, {"time_scale": time_scale})
    svc = NodeService(store, cfg, PlacementService())
    mgr = BaremetalManager(
        store, ResourceLimiter({"baremetal_nodes": 10}), svc, clock
    )
    return mgr, store


def test_legacy_targets_reach_same_final_states_with_time_scale_zero():
    mgr, store = _mgr()
    mgr.create_node("n", "ipmi")
    assert mgr.set_provision_state("n", "manage").provision_state == "manageable"
    assert mgr.set_provision_state("n", "clean").provision_state == "manageable"
    assert mgr.set_provision_state("n", "provide").provision_state == "available"
    node = mgr.set_provision_state("n", "active")
    assert (node.provision_state, node.power_state) == ("active", "power on")
    node = mgr.set_provision_state("n", "deleted")
    assert (node.provision_state, node.power_state) == ("available", "power off")
    assert node.target_provision_state is None and not store.pending
    mgr.set_provision_state("n", "deleted")
    assert mgr.get_node("n") is None


def test_invalid_legacy_transition_raises_invalid_state_error():
    mgr, _ = _mgr()
    mgr.create_node("n", "ipmi")
    with pytest.raises(InvalidStateError):
        mgr.set_provision_state("n", "provide")


def test_reads_sync_due_transitions():
    t = [0.0]
    mgr, store = _mgr(time_scale=1.0, clock=Clock(lambda: t[0]))
    mgr.create_node("n", "ipmi")
    mgr.set_provision_state("n", "manage")
    assert store.baremetal_nodes["n"].provision_state != "manageable"
    t[0] = 10_000.0
    assert mgr.get_node("n").provision_state == "manageable"
