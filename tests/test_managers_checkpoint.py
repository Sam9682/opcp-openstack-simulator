"""Checkpoint test: Verify auth, compute, and network managers work together."""

import pytest

from openstack_simulator.store import ResourceStore
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.auth import AuthManager
from openstack_simulator.managers.compute import ComputeManager
from openstack_simulator.managers.network import NetworkManager
from openstack_simulator.exceptions import (
    AuthenticationError,
    DuplicateResourceError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
    TokenExpiredError,
)


@pytest.fixture
def shared_infrastructure():
    """Create shared store and limiter for all managers."""
    store = ResourceStore()
    limiter = ResourceLimiter(limits={"instances": 3, "networks": 2})
    return store, limiter


@pytest.fixture
def managers(shared_infrastructure):
    """Create all three managers with shared store and limiter."""
    store, limiter = shared_infrastructure
    auth = AuthManager(store=store, session_timeout=120)
    compute = ComputeManager(store=store, limiter=limiter)
    network = NetworkManager(store=store, limiter=limiter)
    return auth, compute, network


class TestManagersInstantiation:
    """Verify all three managers can be imported and instantiated together."""

    def test_managers_share_store(self, managers):
        """All managers reference the same ResourceStore instance."""
        auth, compute, network = managers
        assert auth.store is compute.store
        assert compute.store is network.store

    def test_managers_share_limiter(self, managers):
        """Compute and network managers reference the same ResourceLimiter."""
        _, compute, network = managers
        assert compute.limiter is network.limiter


class TestAuthManager:
    """Verify AuthManager works correctly."""

    def test_authenticate_success(self, managers):
        """Authenticating with valid credentials returns a token."""
        auth, _, _ = managers
        token = auth.authenticate("admin", "secret")
        assert token is not None
        assert token.username == "admin"
        assert token.id is not None
        assert token.issued_at is not None
        assert token.expires_at is not None

    def test_validate_token_success(self, managers):
        """Validating a freshly issued token succeeds."""
        auth, _, _ = managers
        token = auth.authenticate("user1", "pass1")
        assert auth.validate_token(token.id) is True

    def test_authenticate_empty_username_raises(self, managers):
        """Empty username raises AuthenticationError."""
        auth, _, _ = managers
        with pytest.raises(AuthenticationError):
            auth.authenticate("", "password")

    def test_authenticate_empty_password_raises(self, managers):
        """Empty password raises AuthenticationError."""
        auth, _, _ = managers
        with pytest.raises(AuthenticationError):
            auth.authenticate("user", "")

    def test_validate_unknown_token_raises(self, managers):
        """Validating an unknown token raises ResourceNotFoundError."""
        auth, _, _ = managers
        with pytest.raises(ResourceNotFoundError):
            auth.validate_token("nonexistent-token-id")


class TestComputeManager:
    """Verify ComputeManager works correctly."""

    def test_create_instance(self, managers):
        """Creating an instance returns an active instance."""
        _, compute, _ = managers
        instance = compute.create("web-server", "m1.small", "ubuntu-22.04")
        assert instance.name == "web-server"
        assert instance.flavor == "m1.small"
        assert instance.image == "ubuntu-22.04"
        assert instance.status == "ACTIVE"
        assert instance.id is not None
        assert instance.created_at is not None

    def test_get_instance(self, managers):
        """Getting a created instance returns it."""
        _, compute, _ = managers
        compute.create("db-server", "m1.large", "centos-8")
        retrieved = compute.get("db-server")
        assert retrieved is not None
        assert retrieved.name == "db-server"

    def test_get_nonexistent_returns_none(self, managers):
        """Getting a nonexistent instance returns None."""
        _, compute, _ = managers
        assert compute.get("ghost") is None

    def test_duplicate_name_raises(self, managers):
        """Creating two instances with the same name raises DuplicateResourceError."""
        _, compute, _ = managers
        compute.create("dup-server", "m1.small", "ubuntu-22.04")
        with pytest.raises(DuplicateResourceError):
            compute.create("dup-server", "m1.large", "centos-8")

    def test_resource_limit_enforcement(self, managers):
        """Creating beyond the limit raises ResourceLimitExceededError."""
        _, compute, _ = managers
        compute.create("s1", "m1.small", "ubuntu-22.04")
        compute.create("s2", "m1.small", "ubuntu-22.04")
        compute.create("s3", "m1.small", "ubuntu-22.04")
        with pytest.raises(ResourceLimitExceededError):
            compute.create("s4", "m1.small", "ubuntu-22.04")

    def test_delete_and_list(self, managers):
        """Deleting an instance removes it from list."""
        _, compute, _ = managers
        compute.create("temp", "m1.small", "ubuntu-22.04")
        assert len(compute.list()) == 1
        compute.delete("temp")
        assert len(compute.list()) == 0

    def test_delete_nonexistent_raises(self, managers):
        """Deleting a nonexistent instance raises ResourceNotFoundError."""
        _, compute, _ = managers
        with pytest.raises(ResourceNotFoundError):
            compute.delete("ghost")

    def test_resize_instance(self, managers):
        """Resizing an instance updates its flavor."""
        _, compute, _ = managers
        compute.create("resize-me", "m1.small", "ubuntu-22.04")
        resized = compute.resize("resize-me", "m1.xlarge")
        assert resized.flavor == "m1.xlarge"
        assert resized.status == "ACTIVE"

    def test_snapshot_instance(self, managers):
        """Snapshotting an instance creates a snapshot record."""
        _, compute, _ = managers
        instance = compute.create("snap-target", "m1.small", "ubuntu-22.04")
        snap = compute.snapshot("snap-target", "my-snapshot")
        assert snap.name == "my-snapshot"
        assert snap.source_id == instance.id
        assert snap.source_type == "instance"


class TestNetworkManager:
    """Verify NetworkManager works correctly."""

    def test_create_network(self, managers):
        """Creating a network returns an active network."""
        _, _, network = managers
        net = network.create("prod-net")
        assert net.name == "prod-net"
        assert net.status == "ACTIVE"
        assert net.id is not None
        assert net.subnet_ids == []

    def test_get_network(self, managers):
        """Getting a created network returns it."""
        _, _, network = managers
        network.create("test-net")
        retrieved = network.get("test-net")
        assert retrieved is not None
        assert retrieved.name == "test-net"

    def test_get_nonexistent_returns_none(self, managers):
        """Getting a nonexistent network returns None."""
        _, _, network = managers
        assert network.get("ghost-net") is None

    def test_create_subnet(self, managers):
        """Creating a subnet associates it with the network."""
        _, _, network = managers
        net = network.create("subnet-net")
        subnet = network.create_subnet("subnet-net", "my-subnet", "10.0.0.0/24", "10.0.0.1")
        assert subnet.name == "my-subnet"
        assert subnet.network_id == net.id
        assert subnet.cidr == "10.0.0.0/24"
        assert subnet.gateway == "10.0.0.1"
        # Subnet ID should be in network's subnet_ids
        updated_net = network.get("subnet-net")
        assert subnet.id in updated_net.subnet_ids

    def test_create_subnet_nonexistent_network_raises(self, managers):
        """Creating a subnet on a nonexistent network raises ResourceNotFoundError."""
        _, _, network = managers
        with pytest.raises(ResourceNotFoundError):
            network.create_subnet("ghost-net", "sub", "10.0.0.0/24", "10.0.0.1")

    def test_create_router(self, managers):
        """Creating a router returns an active router."""
        _, _, network = managers
        router = network.create_router("main-router")
        assert router.name == "main-router"
        assert router.status == "ACTIVE"
        assert router.subnet_ids == []

    def test_add_router_interface(self, managers):
        """Adding a router interface associates subnet with router."""
        _, _, network = managers
        net = network.create("iface-net")
        subnet = network.create_subnet("iface-net", "iface-sub", "10.0.1.0/24", "10.0.1.1")
        router = network.create_router("iface-router")
        network.add_router_interface("iface-router", subnet.id)
        # Verify subnet is in router's subnet_ids
        updated_router = network.store.get("routers", "iface-router")
        assert subnet.id in updated_router.subnet_ids

    def test_create_port(self, managers):
        """Creating a port on a network returns an active port."""
        _, _, network = managers
        net = network.create("port-net")
        port = network.create_port("port-net", "my-port")
        assert port.name == "my-port"
        assert port.network_id == net.id
        assert port.status == "ACTIVE"
        assert port.mac_address.startswith("fa:16:3e:")

    def test_create_port_nonexistent_network_raises(self, managers):
        """Creating a port on a nonexistent network raises ResourceNotFoundError."""
        _, _, network = managers
        with pytest.raises(ResourceNotFoundError):
            network.create_port("ghost-net", "orphan-port")

    def test_create_bond(self, managers):
        """Creating a bond from existing ports succeeds."""
        _, _, network = managers
        net = network.create("bond-net")
        port1 = network.create_port("bond-net", "port-a")
        port2 = network.create_port("bond-net", "port-b")
        bond = network.create_bond("my-bond", ["port-a", "port-b"], "802.3ad")
        assert bond.name == "my-bond"
        assert bond.bond_mode == "802.3ad"
        assert bond.status == "ACTIVE"
        assert port1.id in bond.port_ids
        assert port2.id in bond.port_ids

    def test_create_bond_nonexistent_port_raises(self, managers):
        """Creating a bond with a nonexistent port raises ResourceNotFoundError."""
        _, _, network = managers
        net = network.create("bond-net2")
        network.create_port("bond-net2", "real-port")
        with pytest.raises(ResourceNotFoundError):
            network.create_bond("bad-bond", ["real-port", "ghost-port"], "802.3ad")

    def test_delete_network(self, managers):
        """Deleting a network removes it from list."""
        _, _, network = managers
        network.create("del-net")
        assert len(network.list()) == 1
        network.delete("del-net")
        assert len(network.list()) == 0

    def test_network_limit_enforcement(self, managers):
        """Creating beyond the network limit raises ResourceLimitExceededError."""
        _, _, network = managers
        network.create("net-1")
        network.create("net-2")
        with pytest.raises(ResourceLimitExceededError):
            network.create("net-3")


class TestIntegrationAllManagers:
    """Full integration test using all three managers together."""

    def test_full_workflow(self, managers):
        """
        End-to-end workflow:
        1. Authenticate a user
        2. Create an instance
        3. Create a network, subnet, router, port, and bond
        4. Verify all operations succeed
        """
        auth, compute, network = managers

        # Step 1: Authenticate
        token = auth.authenticate("lab-user", "lab-pass")
        assert auth.validate_token(token.id) is True

        # Step 2: Create an instance
        instance = compute.create("lab-vm", "m1.small", "ubuntu-22.04")
        assert instance.status == "ACTIVE"
        assert compute.get("lab-vm") is not None

        # Step 3: Create network infrastructure
        net = network.create("lab-network")
        assert net.status == "ACTIVE"

        subnet = network.create_subnet(
            "lab-network", "lab-subnet", "192.168.1.0/24", "192.168.1.1"
        )
        assert subnet.network_id == net.id
        assert subnet.id in network.get("lab-network").subnet_ids

        router = network.create_router("lab-router")
        assert router.status == "ACTIVE"

        network.add_router_interface("lab-router", subnet.id)

        port = network.create_port("lab-network", "lab-port")
        assert port.status == "ACTIVE"
        assert port.network_id == net.id

        bond = network.create_bond("lab-bond", ["lab-port"], "802.3ad")
        assert bond.status == "ACTIVE"
        assert port.id in bond.port_ids

        # Step 4: Verify all resources are accessible
        assert compute.get("lab-vm") is not None
        assert network.get("lab-network") is not None
        assert auth.validate_token(token.id) is True

        # Verify counts
        assert len(compute.list()) == 1
        assert len(network.list()) == 1
