"""Property-based tests for Ironic Baremetal Manager models.

Uses Hypothesis to verify universal correctness properties of the
BaremetalNode and BaremetalPort data models.
"""

import time
import uuid as uuid_mod

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidStateError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.baremetal import BaremetalManager
from openstack_simulator.models import BaremetalPort
from openstack_simulator.store import ResourceStore


# --- Strategies ---

def mac_addresses():
    """Generate random valid MAC addresses in colon-separated hex format."""
    return st.tuples(
        *[st.integers(min_value=0, max_value=255) for _ in range(6)]
    ).map(lambda octets: ":".join(f"{b:02x}" for b in octets))


def valid_port_statuses():
    """Generate valid status values for BaremetalPort."""
    return st.sampled_from(["ACTIVE", "DELETED"])


def iso8601_timestamps():
    """Generate ISO 8601 timestamps similar to those used in the simulator."""
    return st.datetimes().map(lambda dt: dt.isoformat() + "Z") | st.just("")


def uuids():
    """Generate random UUID v4 strings."""
    return st.uuids().map(str)


def baremetal_ports():
    """Generate random valid BaremetalPort instances."""
    return st.builds(
        BaremetalPort,
        id=uuids(),
        node_id=uuids(),
        address=mac_addresses(),
        status=valid_port_statuses(),
        created_at=iso8601_timestamps(),
    )


# Feature: ironic-baremetal-manager, Property 2: BaremetalPort serialization round-trip
class TestBaremetalPortSerializationRoundTrip:
    """Property 2: BaremetalPort serialization round-trip.

    For any valid BaremetalPort instance with arbitrary field values,
    calling BaremetalPort.from_dict(port.to_dict()) SHALL produce a
    BaremetalPort equal to the original.

    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    @given(port=baremetal_ports())
    @settings(max_examples=100)
    def test_port_serialization_round_trip(self, port: BaremetalPort):
        """BaremetalPort survives a to_dict/from_dict round-trip."""
        serialized = port.to_dict()
        deserialized = BaremetalPort.from_dict(serialized)

        assert deserialized.id == port.id
        assert deserialized.node_id == port.node_id
        assert deserialized.address == port.address
        assert deserialized.status == port.status
        assert deserialized.created_at == port.created_at
        assert deserialized == port


# Feature: ironic-baremetal-manager, Property 5: Node quota enforcement
class TestNodeQuotaEnforcement:
    """Property 5: Node quota enforcement.

    For any configured limit N, when exactly N non-deleted baremetal nodes
    exist, attempting to create an additional node SHALL raise
    ResourceLimitExceededError.

    **Validates: Requirements 3.4**
    """

    @given(limit=st.integers(min_value=1, max_value=5))
    @settings(max_examples=100)
    def test_node_quota_enforcement(self, limit: int):
        """Creating N+1 nodes with limit N raises ResourceLimitExceededError."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": limit})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create exactly N nodes (should all succeed)
        for i in range(limit):
            manager.create_node(name=f"node-{i}", driver="fake-driver")

        # The N+1th creation must raise ResourceLimitExceededError
        with pytest.raises(ResourceLimitExceededError):
            manager.create_node(name=f"node-{limit}", driver="fake-driver")


# Feature: ironic-baremetal-manager, Property 6: Node store consistency
class TestNodeStoreConsistency:
    """Property 6: Node store consistency.

    For any sequence of create and delete operations on nodes,
    list_nodes() SHALL return exactly the set of non-deleted nodes,
    get_node(name) SHALL return None for deleted or non-existent names,
    and get_node(name) SHALL return the node for any non-deleted name.

    **Validates: Requirements 3.5, 4.1, 4.2, 4.3, 5.1, 5.3**
    """

    @given(
        data=st.data(),
        num_operations=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100)
    def test_node_store_consistency(self, data, num_operations: int):
        """Create/delete sequences maintain store consistency invariants."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 50})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Track which nodes are alive (non-deleted) and which were deleted
        alive_names: set[str] = set()
        deleted_names: set[str] = set()
        node_counter = 0

        for _ in range(num_operations):
            # Decide whether to create or delete
            # If no alive nodes, always create; otherwise pick randomly
            if alive_names:
                action = data.draw(st.sampled_from(["create", "delete"]))
            else:
                action = "create"

            if action == "create":
                name = f"node-{node_counter}"
                node_counter += 1
                manager.create_node(name=name, driver="fake-driver")
                alive_names.add(name)
            else:
                # Delete a random alive node
                name_to_delete = data.draw(
                    st.sampled_from(sorted(alive_names))
                )
                manager.delete_node(name_to_delete)
                alive_names.discard(name_to_delete)
                deleted_names.add(name_to_delete)

        # Verify invariant 1: list_nodes() returns exactly the non-deleted nodes
        listed_nodes = manager.list_nodes()
        listed_names = {n.name for n in listed_nodes}
        assert listed_names == alive_names

        # Verify invariant 2: get_node returns None for deleted names
        for name in deleted_names:
            assert manager.get_node(name) is None

        # Verify invariant 3: get_node returns None for non-existent names
        non_existent_name = f"node-never-created-{node_counter + 100}"
        assert manager.get_node(non_existent_name) is None

        # Verify invariant 4: get_node returns the node for alive names
        for name in alive_names:
            node = manager.get_node(name)
            assert node is not None
            assert node.name == name


# Feature: ironic-baremetal-manager, Property 3: Node creation initial state invariant
class TestNodeCreationInitialState:
    """Property 3: Node creation initial state invariant.

    For any valid name/driver/hardware params, verify newly created node
    has provision_state=="enroll" and power_state=="power off".

    **Validates: Requirements 3.1**
    """

    @given(
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=50,
        ),
        driver=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=30,
        ),
        memory_mb=st.integers(min_value=0, max_value=1048576),
        cpus=st.integers(min_value=0, max_value=1024),
        local_gb=st.integers(min_value=0, max_value=100000),
        cpu_arch=st.sampled_from(["x86_64", "aarch64", "ppc64le", "s390x"]),
    )
    @settings(max_examples=100)
    def test_node_creation_initial_state(
        self,
        name: str,
        driver: str,
        memory_mb: int,
        cpus: int,
        local_gb: int,
        cpu_arch: str,
    ):
        """Newly created node always has provision_state='enroll' and power_state='power off'."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        node = manager.create_node(
            name=name,
            driver=driver,
            memory_mb=memory_mb,
            cpus=cpus,
            local_gb=local_gb,
            cpu_arch=cpu_arch,
        )

        assert node.provision_state == "enroll"
        assert node.power_state == "power off"


# Feature: ironic-baremetal-manager, Property 4: Duplicate node name rejection
class TestDuplicateNodeNameRejection:
    """Property 4: Duplicate node name rejection.

    For any node name, if a non-deleted node with that name already exists,
    attempting to create another node with the same name SHALL raise
    DuplicateResourceError.

    **Validates: Requirements 3.3**
    """

    @given(
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=50,
        ),
        driver1=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=30,
        ),
        driver2=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
            min_size=1,
            max_size=30,
        ),
    )
    @settings(max_examples=100)
    def test_duplicate_node_name_rejected(
        self, name: str, driver1: str, driver2: str
    ):
        """Creating a node with a name that already exists raises DuplicateResourceError."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # First creation should succeed
        manager.create_node(name=name, driver=driver1)

        # Second creation with the same name must raise DuplicateResourceError
        with pytest.raises(DuplicateResourceError):
            manager.create_node(name=name, driver=driver2)


# Feature: ironic-baremetal-manager, Property 8: Invalid provision state transitions
class TestInvalidProvisionStateTransitions:
    """Property 8: Invalid provision state transitions.

    For any node and any target that is not a valid transition from the
    node's current provision_state, set_provision_state SHALL raise
    InvalidStateError.

    **Validates: Requirements 6.6**
    """

    # Valid transitions map: state -> set of valid targets
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "enroll": {"manage"},
        "manageable": {"provide", "clean"},
        "available": {"active", "deleted"},
        "active": {"deleted"},
    }

    # All known targets across all states
    ALL_TARGETS = ["manage", "provide", "clean", "active", "deleted", "power on", "power off", "rebooting", "inspect", "rebuild"]

    @given(
        data=st.data(),
        source_state=st.sampled_from(["enroll", "manageable", "available", "active"]),
    )
    @settings(max_examples=100)
    def test_invalid_provision_state_raises_error(self, data, source_state: str):
        """Any target not valid for the current provision_state raises InvalidStateError."""
        valid_targets = self.VALID_TRANSITIONS[source_state]

        # Generate a target that is NOT in the valid set for this state
        invalid_targets = [t for t in self.ALL_TARGETS if t not in valid_targets]
        target = data.draw(st.sampled_from(invalid_targets))

        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node and advance it to the source state
        node = manager.create_node(name="test-node", driver="fake-driver")

        # Advance node to the desired source state
        if source_state == "manageable":
            manager.set_provision_state("test-node", "manage")
        elif source_state == "available":
            manager.set_provision_state("test-node", "manage")
            manager.set_provision_state("test-node", "provide")
        elif source_state == "active":
            manager.set_provision_state("test-node", "manage")
            manager.set_provision_state("test-node", "provide")
            manager.set_provision_state("test-node", "active")

        # Verify the node is in the expected source state
        current_node = manager.get_node("test-node")
        assert current_node.provision_state == source_state

        # Attempting an invalid transition must raise InvalidStateError
        with pytest.raises(InvalidStateError):
            manager.set_provision_state("test-node", target)


# Feature: ironic-baremetal-manager, Property 9: Valid power state transitions
class TestValidPowerStateTransitions:
    """Property 9: Valid power state transitions.

    For any node with provision_state in {"available", "active"}, setting
    power state to "power on" or "power off" SHALL update power_state
    accordingly, and setting "rebooting" on a powered-on node SHALL result
    in power_state "power on".

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    def _create_node_in_state(
        self, manager: BaremetalManager, name: str, target_provision_state: str
    ) -> None:
        """Create a node and advance it to the target provision state.

        Supports "available" (enroll→manage→provide) and
        "active" (enroll→manage→provide→active).
        """
        manager.create_node(name=name, driver="fake-driver")
        manager.set_provision_state(name, "manage")
        manager.set_provision_state(name, "provide")
        if target_provision_state == "active":
            manager.set_provision_state(name, "active")

    @given(
        provision_state=st.sampled_from(["available", "active"]),
        power_target=st.sampled_from(["power on", "power off"]),
    )
    @settings(max_examples=100)
    def test_power_on_off_transitions(self, provision_state: str, power_target: str):
        """Node in available/active state can be powered on or off."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        node_name = "test-node"
        self._create_node_in_state(manager, node_name, provision_state)

        result = manager.set_power_state(node_name, power_target)

        assert result.power_state == power_target
        assert result.provision_state == provision_state

    @given(
        provision_state=st.sampled_from(["available", "active"]),
    )
    @settings(max_examples=100)
    def test_rebooting_transition(self, provision_state: str):
        """Node with power_state 'power on' can be rebooted, resulting in power_state 'power on'."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        node_name = "test-node"
        self._create_node_in_state(manager, node_name, provision_state)

        # Ensure node is powered on first
        manager.set_power_state(node_name, "power on")

        # Reboot should result in power_state "power on"
        result = manager.set_power_state(node_name, "rebooting")

        assert result.power_state == "power on"
        assert result.provision_state == provision_state


# Feature: ironic-baremetal-manager, Property 10: Invalid power state transitions
class TestInvalidPowerStateTransitions:
    """Property 10: Invalid power state transitions.

    For any node with provision_state in {enroll, manageable}, any
    set_power_state call SHALL raise InvalidStateError.

    **Validates: Requirements 7.4**
    """

    @given(
        provision_state=st.sampled_from(["enroll", "manageable"]),
        power_target=st.sampled_from(["power on", "power off", "rebooting"]),
    )
    @settings(max_examples=100)
    def test_invalid_power_state_transitions(
        self, provision_state: str, power_target: str
    ):
        """Power state changes on nodes in enroll/manageable raise InvalidStateError."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node (starts in "enroll")
        node = manager.create_node(name="test-node", driver="fake-driver")

        # Optionally advance to "manageable"
        if provision_state == "manageable":
            manager.set_provision_state("test-node", "manage")

        # Verify that any set_power_state call raises InvalidStateError
        with pytest.raises(InvalidStateError):
            manager.set_power_state("test-node", power_target)


# Feature: ironic-baremetal-manager, Property 11: Mutation updates timestamp
class TestMutationUpdatesTimestamp:
    """Property 11: Mutation updates timestamp.

    For any successful state transition (provision or power) or node update,
    the node's updated_at field SHALL be updated to a timestamp later than
    or equal to the previous value.

    **Validates: Requirements 6.7, 7.5, 12.4**
    """

    @given(
        mutation_type=st.sampled_from([
            "provision_manage",
            "provision_provide",
            "provision_active",
            "power_on",
            "power_off",
            "update_driver",
        ]),
    )
    @settings(max_examples=100)
    def test_mutation_updates_timestamp(self, mutation_type: str):
        """Any successful mutation updates updated_at to a value >= previous."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node and advance it to the appropriate state for the mutation
        node = manager.create_node(name="test-node", driver="fake-driver")

        if mutation_type == "provision_manage":
            # Transition: enroll -> manageable
            old_updated_at = node.updated_at
            updated_node = manager.set_provision_state("test-node", "manage")
            assert updated_node.updated_at >= old_updated_at

        elif mutation_type == "provision_provide":
            # Advance to manageable first, then transition: manageable -> available
            manager.set_provision_state("test-node", "manage")
            node = manager.get_node("test-node")
            old_updated_at = node.updated_at
            updated_node = manager.set_provision_state("test-node", "provide")
            assert updated_node.updated_at >= old_updated_at

        elif mutation_type == "provision_active":
            # Advance to available first, then transition: available -> active
            manager.set_provision_state("test-node", "manage")
            manager.set_provision_state("test-node", "provide")
            node = manager.get_node("test-node")
            old_updated_at = node.updated_at
            updated_node = manager.set_provision_state("test-node", "active")
            assert updated_node.updated_at >= old_updated_at

        elif mutation_type == "power_on":
            # Advance to available, then change power state
            manager.set_provision_state("test-node", "manage")
            manager.set_provision_state("test-node", "provide")
            node = manager.get_node("test-node")
            old_updated_at = node.updated_at
            updated_node = manager.set_power_state("test-node", "power on")
            assert updated_node.updated_at >= old_updated_at

        elif mutation_type == "power_off":
            # Advance to available, power on, then power off
            manager.set_provision_state("test-node", "manage")
            manager.set_provision_state("test-node", "provide")
            manager.set_power_state("test-node", "power on")
            node = manager.get_node("test-node")
            old_updated_at = node.updated_at
            updated_node = manager.set_power_state("test-node", "power off")
            assert updated_node.updated_at >= old_updated_at

        elif mutation_type == "update_driver":
            # Update node properties
            old_updated_at = node.updated_at
            updated_node = manager.update_node("test-node", driver="new-driver")
            assert updated_node.updated_at >= old_updated_at


# Feature: ironic-baremetal-manager, Property 14: Duplicate port MAC rejection
class TestDuplicatePortMacRejection:
    """Property 14: Duplicate port MAC rejection.

    For any MAC address, if a non-deleted port with that address already exists,
    attempting to create another port with the same address SHALL raise
    DuplicateResourceError.

    **Validates: Requirements 8.3**
    """

    @given(mac=mac_addresses())
    @settings(max_examples=100)
    def test_duplicate_port_mac_rejected(self, mac: str):
        """Creating a port with a MAC that already exists raises DuplicateResourceError."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100, "baremetal_ports": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node first (ports require a valid node_id)
        node = manager.create_node(name="test-node", driver="fake-driver")

        # First port creation should succeed
        manager.create_port(node_id=node.id, address=mac)

        # Second port creation with the same MAC must raise DuplicateResourceError
        with pytest.raises(DuplicateResourceError):
            manager.create_port(node_id=node.id, address=mac)


# Feature: ironic-baremetal-manager, Property 7: Valid provision state transitions
class TestValidProvisionStateTransitions:
    """Property 7: Valid provision state transitions.

    For each valid (source_state, target) pair, verify the node transitions
    to the expected destination state with correct side effects.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    """

    # Each tuple: (source_state, target, expected_provision_state, expected_power_state)
    VALID_TRANSITIONS = [
        ("enroll", "manage", "manageable", None),
        ("manageable", "provide", "available", None),
        ("manageable", "clean", "manageable", None),
        ("available", "active", "active", "power on"),
        ("active", "deleted", "available", "power off"),
    ]

    def _advance_node_to_state(
        self, manager: BaremetalManager, name: str, target_state: str
    ) -> None:
        """Advance a freshly created node (in 'enroll') to the target provision state."""
        if target_state == "enroll":
            return
        manager.set_provision_state(name, "manage")
        if target_state == "manageable":
            return
        manager.set_provision_state(name, "provide")
        if target_state == "available":
            return
        manager.set_provision_state(name, "active")

    @given(
        transition=st.sampled_from(VALID_TRANSITIONS),
    )
    @settings(max_examples=100)
    def test_valid_provision_state_transitions(self, transition):
        """Valid (source_state, target) pairs produce the expected destination state and side effects."""
        source_state, target, expected_provision_state, expected_power_state = transition

        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node and advance it to the source state
        node_name = "test-node"
        manager.create_node(name=node_name, driver="fake-driver")
        self._advance_node_to_state(manager, node_name, source_state)

        # Verify the node is in the expected source state before transition
        node = manager.get_node(node_name)
        assert node.provision_state == source_state

        # Apply the transition
        result = manager.set_provision_state(node_name, target)

        # Verify the node transitioned to the expected provision state
        assert result.provision_state == expected_provision_state

        # Verify power_state side effects where applicable
        if expected_power_state is not None:
            assert result.power_state == expected_power_state


# Feature: ironic-baremetal-manager, Property 15: Port listing with node filter
class TestPortListingWithNodeFilter:
    """Property 15: Port listing with node filter.

    For any node_id, list_ports(node_id=node_id) SHALL return exactly the set
    of non-deleted ports whose node_id matches the filter, and no others.

    **Validates: Requirements 8.4, 8.5**
    """

    @given(
        data=st.data(),
        num_nodes=st.integers(min_value=2, max_value=3),
        num_ports=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=100)
    def test_port_listing_with_node_filter(self, data, num_nodes: int, num_ports: int):
        """Create ports on multiple nodes, verify list_ports(node_id=X) returns exactly the ports for that node."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 50, "baremetal_ports": 50})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create multiple nodes
        nodes = []
        for i in range(num_nodes):
            node = manager.create_node(name=f"node-{i}", driver="fake-driver")
            nodes.append(node)

        node_ids = [n.id for n in nodes]

        # Distribute ports randomly across nodes using unique MAC addresses
        # Track which ports belong to which node
        ports_by_node: dict[str, list[BaremetalPort]] = {nid: [] for nid in node_ids}
        all_created_ports: list[BaremetalPort] = []

        for i in range(num_ports):
            # Pick a random node to assign this port to
            target_node_id = data.draw(st.sampled_from(node_ids))
            # Generate a unique MAC address for each port
            mac = f"aa:bb:cc:dd:{i // 256:02x}:{i % 256:02x}"
            port = manager.create_port(node_id=target_node_id, address=mac)
            ports_by_node[target_node_id].append(port)
            all_created_ports.append(port)

        # Verify: list_ports(node_id=X) returns exactly the ports for that node
        for node_id in node_ids:
            filtered_ports = manager.list_ports(node_id=node_id)
            expected_ports = ports_by_node[node_id]

            # Same count
            assert len(filtered_ports) == len(expected_ports)

            # Same set of port IDs
            filtered_ids = {p.id for p in filtered_ports}
            expected_ids = {p.id for p in expected_ports}
            assert filtered_ids == expected_ids

            # All returned ports have the correct node_id
            for port in filtered_ports:
                assert port.node_id == node_id

        # Verify: list_ports() without filter returns all ports
        all_ports = manager.list_ports()
        assert len(all_ports) == num_ports
        all_port_ids = {p.id for p in all_ports}
        expected_all_ids = {p.id for p in all_created_ports}
        assert all_port_ids == expected_all_ids


# Feature: ironic-baremetal-manager, Property 13: Port creation with invalid node
class TestPortCreationWithInvalidNode:
    """Property 13: Port creation with invalid node.

    For any node_id not corresponding to an existing non-deleted node,
    verify create_port raises ResourceNotFoundError.

    **Validates: Requirements 8.2**
    """

    @given(
        node_id=st.uuids().map(str),
        address=mac_addresses(),
    )
    @settings(max_examples=100)
    def test_port_creation_with_invalid_node_raises_error(
        self, node_id: str, address: str
    ):
        """Creating a port with a node_id that doesn't exist raises ResourceNotFoundError."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_ports": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # No nodes exist in the store, so any node_id is invalid
        with pytest.raises(ResourceNotFoundError):
            manager.create_port(node_id=node_id, address=address)


# Feature: ironic-baremetal-manager, Property 12: Port creation with valid node
class TestPortCreationWithValidNode:
    """Property 12: Port creation with valid node.

    For any valid MAC address and existing non-deleted node, create_port
    SHALL produce a BaremetalPort with a valid UUID id, the correct node_id,
    and an ISO 8601 created_at timestamp.

    **Validates: Requirements 8.1**
    """

    @given(mac=mac_addresses())
    @settings(max_examples=100)
    def test_port_creation_with_valid_node(self, mac: str):
        """create_port with a valid node produces a port with valid UUID, correct node_id, and non-empty created_at."""
        store = ResourceStore()
        limiter = ResourceLimiter({"baremetal_nodes": 100, "baremetal_ports": 100})
        manager = BaremetalManager(store=store, limiter=limiter)

        # Create a node first to get a valid node_id
        node = manager.create_node(name="test-node", driver="fake-driver")
        node_id = node.id

        # Create a port with the generated MAC address
        port = manager.create_port(node_id=node_id, address=mac)

        # Verify the port has a valid UUID id
        parsed_uuid = uuid_mod.UUID(port.id)
        assert str(parsed_uuid) == port.id

        # Verify the port has the correct node_id
        assert port.node_id == node_id

        # Verify created_at is a non-empty string (ISO 8601 timestamp)
        assert port.created_at != ""
        assert isinstance(port.created_at, str)
        assert len(port.created_at) > 0
