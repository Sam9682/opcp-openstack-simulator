"""Checkpoint test: Verify ALL five managers (auth, compute, network, volume, security_group) work together."""

import pytest

from openstack_simulator.store import ResourceStore
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.auth import AuthManager
from openstack_simulator.managers.compute import ComputeManager
from openstack_simulator.managers.network import NetworkManager
from openstack_simulator.managers.volume import VolumeManager
from openstack_simulator.managers.security_group import SecurityGroupManager
from openstack_simulator.exceptions import (
    AuthenticationError,
    DuplicateResourceError,
    InvalidStateError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
    TokenExpiredError,
)


@pytest.fixture
def shared_infrastructure():
    """Create shared store and limiter for all five managers."""
    store = ResourceStore()
    limiter = ResourceLimiter(
        limits={
            "instances": 3,
            "networks": 2,
            "volumes": 3,
            "security_groups": 5,
        }
    )
    return store, limiter


@pytest.fixture
def all_managers(shared_infrastructure):
    """Create all five managers with shared store and limiter."""
    store, limiter = shared_infrastructure
    auth = AuthManager(store=store, session_timeout=120)
    compute = ComputeManager(store=store, limiter=limiter)
    network = NetworkManager(store=store, limiter=limiter)
    volume = VolumeManager(store=store, limiter=limiter)
    security_group = SecurityGroupManager(store=store, limiter=limiter)
    return auth, compute, network, volume, security_group


class TestAllManagersInstantiation:
    """Verify all five managers can be imported and instantiated together."""

    def test_all_managers_share_store(self, all_managers):
        """All five managers reference the same ResourceStore instance."""
        auth, compute, network, volume, security_group = all_managers
        assert auth.store is compute.store
        assert compute.store is network.store
        assert network.store is volume.store
        assert volume.store is security_group.store

    def test_limited_managers_share_limiter(self, all_managers):
        """Compute, network, volume, and security_group managers share the same limiter."""
        _, compute, network, volume, security_group = all_managers
        assert compute.limiter is network.limiter
        assert network.limiter is volume.limiter
        assert volume.limiter is security_group.limiter


class TestVolumeManager:
    """Verify VolumeManager works correctly."""

    def test_create_volume(self, all_managers):
        """Creating a volume returns an available volume."""
        _, _, _, volume, _ = all_managers
        vol = volume.create("data-vol", 100)
        assert vol.name == "data-vol"
        assert vol.size == 100
        assert vol.status == "available"
        assert vol.attached_to is None
        assert vol.id is not None
        assert vol.created_at is not None

    def test_get_volume(self, all_managers):
        """Getting a created volume returns it."""
        _, _, _, volume, _ = all_managers
        volume.create("test-vol", 50)
        retrieved = volume.get("test-vol")
        assert retrieved is not None
        assert retrieved.name == "test-vol"
        assert retrieved.size == 50

    def test_get_nonexistent_returns_none(self, all_managers):
        """Getting a nonexistent volume returns None."""
        _, _, _, volume, _ = all_managers
        assert volume.get("ghost-vol") is None

    def test_duplicate_name_raises(self, all_managers):
        """Creating two volumes with the same name raises DuplicateResourceError."""
        _, _, _, volume, _ = all_managers
        volume.create("dup-vol", 10)
        with pytest.raises(DuplicateResourceError):
            volume.create("dup-vol", 20)

    def test_resource_limit_enforcement(self, all_managers):
        """Creating beyond the volume limit raises ResourceLimitExceededError."""
        _, _, _, volume, _ = all_managers
        volume.create("v1", 10)
        volume.create("v2", 20)
        volume.create("v3", 30)
        with pytest.raises(ResourceLimitExceededError):
            volume.create("v4", 40)

    def test_attach_volume(self, all_managers):
        """Attaching a volume to an instance updates status and attached_to."""
        _, compute, _, volume, _ = all_managers
        compute.create("attach-vm", "m1.small", "ubuntu-22.04")
        vol = volume.create("attach-vol", 50)
        attached = volume.attach("attach-vol", "attach-vm")
        assert attached.status == "in-use"
        assert attached.attached_to == "attach-vm"

    def test_attach_nonexistent_volume_raises(self, all_managers):
        """Attaching a nonexistent volume raises ResourceNotFoundError."""
        _, compute, _, volume, _ = all_managers
        compute.create("some-vm", "m1.small", "ubuntu-22.04")
        with pytest.raises(ResourceNotFoundError):
            volume.attach("ghost-vol", "some-vm")

    def test_attach_to_nonexistent_instance_raises(self, all_managers):
        """Attaching to a nonexistent instance raises ResourceNotFoundError."""
        _, _, _, volume, _ = all_managers
        volume.create("orphan-vol", 50)
        with pytest.raises(ResourceNotFoundError):
            volume.attach("orphan-vol", "ghost-vm")

    def test_double_attach_raises(self, all_managers):
        """Attaching an already in-use volume raises InvalidStateError."""
        _, compute, _, volume, _ = all_managers
        compute.create("vm1", "m1.small", "ubuntu-22.04")
        compute.create("vm2", "m1.small", "ubuntu-22.04")
        volume.create("busy-vol", 50)
        volume.attach("busy-vol", "vm1")
        with pytest.raises(InvalidStateError):
            volume.attach("busy-vol", "vm2")

    def test_delete_available_volume(self, all_managers):
        """Deleting an available volume removes it from list."""
        _, _, _, volume, _ = all_managers
        volume.create("del-vol", 10)
        assert len(volume.list()) == 1
        volume.delete("del-vol")
        assert len(volume.list()) == 0

    def test_delete_in_use_volume_raises(self, all_managers):
        """Deleting an in-use volume raises InvalidStateError."""
        _, compute, _, volume, _ = all_managers
        compute.create("del-vm", "m1.small", "ubuntu-22.04")
        volume.create("in-use-vol", 50)
        volume.attach("in-use-vol", "del-vm")
        with pytest.raises(InvalidStateError):
            volume.delete("in-use-vol")

    def test_snapshot_volume(self, all_managers):
        """Snapshotting a volume creates a snapshot record."""
        _, _, _, volume, _ = all_managers
        vol = volume.create("snap-vol", 100)
        snap = volume.snapshot("snap-vol", "vol-snapshot")
        assert snap.name == "vol-snapshot"
        assert snap.source_id == vol.id
        assert snap.source_type == "volume"


class TestSecurityGroupManager:
    """Verify SecurityGroupManager works correctly."""

    def test_create_security_group(self, all_managers):
        """Creating a security group returns an active group."""
        _, _, _, _, sg_mgr = all_managers
        sg = sg_mgr.create("web-sg", "Allow web traffic")
        assert sg.name == "web-sg"
        assert sg.description == "Allow web traffic"
        assert sg.status == "ACTIVE"
        assert sg.rules == []
        assert sg.id is not None
        assert sg.created_at is not None

    def test_get_security_group(self, all_managers):
        """Getting a created security group returns it."""
        _, _, _, _, sg_mgr = all_managers
        sg_mgr.create("test-sg", "Test group")
        retrieved = sg_mgr.get("test-sg")
        assert retrieved is not None
        assert retrieved.name == "test-sg"

    def test_get_nonexistent_returns_none(self, all_managers):
        """Getting a nonexistent security group returns None."""
        _, _, _, _, sg_mgr = all_managers
        assert sg_mgr.get("ghost-sg") is None

    def test_duplicate_name_raises(self, all_managers):
        """Creating two security groups with the same name raises DuplicateResourceError."""
        _, _, _, _, sg_mgr = all_managers
        sg_mgr.create("dup-sg", "First")
        with pytest.raises(DuplicateResourceError):
            sg_mgr.create("dup-sg", "Second")

    def test_resource_limit_enforcement(self, all_managers):
        """Creating beyond the security group limit raises ResourceLimitExceededError."""
        _, _, _, _, sg_mgr = all_managers
        for i in range(5):
            sg_mgr.create(f"sg-{i}", f"Group {i}")
        with pytest.raises(ResourceLimitExceededError):
            sg_mgr.create("sg-overflow", "Too many")

    def test_add_rule(self, all_managers):
        """Adding a rule to a security group succeeds."""
        _, _, _, _, sg_mgr = all_managers
        sg = sg_mgr.create("rule-sg", "For rules")
        rule = sg_mgr.add_rule("rule-sg", "tcp", "80:80", "ingress", "0.0.0.0/0")
        assert rule.protocol == "tcp"
        assert rule.port_range == "80:80"
        assert rule.direction == "ingress"
        assert rule.remote_ip_prefix == "0.0.0.0/0"
        assert rule.security_group_id == sg.id
        # Rule should be in the security group's rules list
        updated_sg = sg_mgr.get("rule-sg")
        assert len(updated_sg.rules) == 1
        assert updated_sg.rules[0].id == rule.id

    def test_add_rule_nonexistent_sg_raises(self, all_managers):
        """Adding a rule to a nonexistent security group raises ResourceNotFoundError."""
        _, _, _, _, sg_mgr = all_managers
        with pytest.raises(ResourceNotFoundError):
            sg_mgr.add_rule("ghost-sg", "tcp", "443:443", "ingress", "0.0.0.0/0")

    def test_delete_rule(self, all_managers):
        """Deleting a rule removes it from the security group."""
        _, _, _, _, sg_mgr = all_managers
        sg_mgr.create("del-rule-sg", "For deletion")
        rule = sg_mgr.add_rule("del-rule-sg", "udp", "53:53", "egress", "10.0.0.0/8")
        sg_mgr.delete_rule(rule.id)
        updated_sg = sg_mgr.get("del-rule-sg")
        assert len(updated_sg.rules) == 0

    def test_delete_security_group(self, all_managers):
        """Deleting a security group removes it from list."""
        _, _, _, _, sg_mgr = all_managers
        sg_mgr.create("del-sg", "To delete")
        assert len(sg_mgr.list()) == 1
        sg_mgr.delete("del-sg")
        assert len(sg_mgr.list()) == 0

    def test_delete_nonexistent_raises(self, all_managers):
        """Deleting a nonexistent security group raises ResourceNotFoundError."""
        _, _, _, _, sg_mgr = all_managers
        with pytest.raises(ResourceNotFoundError):
            sg_mgr.delete("ghost-sg")


class TestFullIntegrationAllFiveManagers:
    """Full integration test exercising all five managers together."""

    def test_complete_workflow(self, all_managers):
        """
        End-to-end workflow using all five managers:
        1. Authenticate a user
        2. Create an instance
        3. Create a network with subnet
        4. Create a volume and attach it to the instance
        5. Create a security group and add a rule
        6. Verify all operations succeed and resources are accessible
        """
        auth, compute, network, volume, security_group = all_managers

        # Step 1: Authenticate a user
        token = auth.authenticate("lab-user", "lab-pass")
        assert token is not None
        assert token.username == "lab-user"
        assert auth.validate_token(token.id) is True

        # Step 2: Create an instance
        instance = compute.create("web-server", "m1.small", "ubuntu-22.04")
        assert instance.status == "ACTIVE"
        assert instance.name == "web-server"

        # Step 3: Create a network with subnet
        net = network.create("app-network")
        assert net.status == "ACTIVE"
        subnet = network.create_subnet(
            "app-network", "app-subnet", "10.0.0.0/24", "10.0.0.1"
        )
        assert subnet.network_id == net.id
        assert subnet.id in network.get("app-network").subnet_ids

        # Step 4: Create a volume and attach it to the instance
        vol = volume.create("data-disk", 100)
        assert vol.status == "available"
        assert vol.attached_to is None
        attached_vol = volume.attach("data-disk", "web-server")
        assert attached_vol.status == "in-use"
        assert attached_vol.attached_to == "web-server"

        # Step 5: Create a security group and add a rule
        sg = security_group.create("web-sg", "Allow HTTP traffic")
        assert sg.status == "ACTIVE"
        assert sg.rules == []
        rule = security_group.add_rule(
            "web-sg", "tcp", "80:80", "ingress", "0.0.0.0/0"
        )
        assert rule.protocol == "tcp"
        assert rule.port_range == "80:80"
        assert rule.direction == "ingress"
        assert rule.security_group_id == sg.id

        # Step 6: Verify all resources are accessible
        assert compute.get("web-server") is not None
        assert network.get("app-network") is not None
        assert volume.get("data-disk") is not None
        assert volume.get("data-disk").status == "in-use"
        assert security_group.get("web-sg") is not None
        assert len(security_group.get("web-sg").rules) == 1
        assert auth.validate_token(token.id) is True

        # Verify counts
        assert len(compute.list()) == 1
        assert len(network.list()) == 1
        assert len(volume.list()) == 1
        assert len(security_group.list()) == 1

    def test_cross_manager_interactions(self, all_managers):
        """Test that operations across managers interact correctly via shared store."""
        auth, compute, network, volume, security_group = all_managers

        # Create resources across all managers
        auth.authenticate("admin", "admin-pass")
        compute.create("vm-1", "m1.large", "centos-8")
        compute.create("vm-2", "m1.small", "ubuntu-22.04")
        network.create("net-1")
        volume.create("vol-1", 50)
        volume.create("vol-2", 100)
        security_group.create("sg-1", "Group 1")
        security_group.create("sg-2", "Group 2")

        # Attach volumes to different instances
        volume.attach("vol-1", "vm-1")
        volume.attach("vol-2", "vm-2")

        # Add rules to security groups
        security_group.add_rule("sg-1", "tcp", "22:22", "ingress", "10.0.0.0/8")
        security_group.add_rule("sg-1", "tcp", "443:443", "ingress", "0.0.0.0/0")
        security_group.add_rule("sg-2", "icmp", "-1:-1", "ingress", "0.0.0.0/0")

        # Verify all resources coexist in the shared store
        assert len(compute.list()) == 2
        assert len(network.list()) == 1
        assert len(volume.list()) == 2
        assert len(security_group.list()) == 2
        assert len(security_group.get("sg-1").rules) == 2
        assert len(security_group.get("sg-2").rules) == 1

        # Delete an instance - volume should still be in-use
        compute.delete("vm-1")
        assert compute.get("vm-1") is None
        assert volume.get("vol-1").status == "in-use"
        assert volume.get("vol-1").attached_to == "vm-1"

        # Verify remaining resources are unaffected
        assert compute.get("vm-2") is not None
        assert len(compute.list()) == 1
        assert len(volume.list()) == 2
