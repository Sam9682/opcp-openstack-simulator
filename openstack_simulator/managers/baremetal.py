"""Simulated Ironic baremetal manager for the OpenStack Simulator."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidStateError,
    ResourceNotFoundError,
)
from openstack_simulator.models import BaremetalNode, BaremetalPort

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


class BaremetalManager:
    """Simulated Ironic baremetal manager."""

    def __init__(self, store: ResourceStore, limiter: ResourceLimiter) -> None:
        self.store = store
        self.limiter = limiter

    def create_node(
        self,
        name: str,
        driver: str,
        memory_mb: int = 0,
        cpus: int = 0,
        local_gb: int = 0,
        cpu_arch: str = "x86_64",
        driver_info: dict | None = None,
        properties: dict | None = None,
    ) -> BaremetalNode:
        """Create a new baremetal node.

        Raises:
            ResourceLimitExceededError: If max_baremetal_nodes reached.
            DuplicateResourceError: If name already exists (non-deleted).
        """
        self.limiter.check("baremetal_nodes", self.store)

        existing = self.store.get("baremetal_nodes", name)
        if existing is not None:
            raise DuplicateResourceError(
                f"Baremetal node '{name}' already exists"
            )

        now = datetime.now(timezone.utc).isoformat()
        node = BaremetalNode(
            id=str(uuid.uuid4()),
            name=name,
            driver=driver,
            power_state="power off",
            provision_state="enroll",
            memory_mb=memory_mb,
            cpus=cpus,
            local_gb=local_gb,
            cpu_arch=cpu_arch,
            driver_info=driver_info if driver_info is not None else {},
            properties=properties if properties is not None else {},
            status="ACTIVE",
            created_at=now,
            updated_at=now,
        )
        self.store.add("baremetal_nodes", name, node)
        return node

    def get_node(self, name: str) -> BaremetalNode | None:
        """Get a baremetal node by name. Returns None if not found."""
        return self.store.get("baremetal_nodes", name)

    def list_nodes(self) -> list[BaremetalNode]:
        """Return all non-deleted baremetal nodes."""
        return self.store.list_active("baremetal_nodes")

    def update_node(self, node_name: str, **updates) -> BaremetalNode:
        """Update a baremetal node's properties.

        Args:
            node_name: The current name of the node to update.
            **updates: Key-value pairs of fields to update.

        Raises:
            ResourceNotFoundError: If node not found.
            DuplicateResourceError: If new name already exists.
        """
        node = self.store.get("baremetal_nodes", node_name)
        if node is None:
            raise ResourceNotFoundError(
                f"Baremetal node '{node_name}' not found"
            )

        # Check for duplicate name if name is being changed
        new_name = updates.get("name")
        if new_name is not None and new_name != node_name:
            existing = self.store.get("baremetal_nodes", new_name)
            if existing is not None:
                raise DuplicateResourceError(
                    f"Baremetal node '{new_name}' already exists"
                )

        # Apply updates to the node
        for key, value in updates.items():
            if hasattr(node, key):
                setattr(node, key, value)

        # Update timestamp
        node.updated_at = datetime.now(timezone.utc).isoformat()

        # If name changed, re-key in the store
        if new_name is not None and new_name != node_name:
            # Remove old entry and add with new name
            del self.store.baremetal_nodes[node_name]
            self.store.add("baremetal_nodes", new_name, node)

        return node

    def delete_node(self, name: str) -> None:
        """Soft-delete a baremetal node.

        Raises:
            ResourceNotFoundError: If node not found.
        """
        node = self.store.get("baremetal_nodes", name)
        if node is None:
            raise ResourceNotFoundError(f"Baremetal node '{name}' not found")

        node.provision_state = "deleted"
        self.store.mark_deleted("baremetal_nodes", name)

    # --- Port operations ---

    def create_port(self, node_id: str, address: str) -> BaremetalPort:
        """Create a new baremetal port.

        Args:
            node_id: UUID of the parent node (the node's id field).
            address: MAC address for the port.

        Raises:
            ResourceLimitExceededError: If max_baremetal_ports reached.
            ResourceNotFoundError: If node_id does not reference an existing non-deleted node.
            DuplicateResourceError: If MAC address already exists among non-deleted ports.
        """
        self.limiter.check("baremetal_ports", self.store)

        # Verify node_id references an existing non-deleted node (search by id field)
        active_nodes = self.store.list_active("baremetal_nodes")
        node_exists = any(node.id == node_id for node in active_nodes)
        if not node_exists:
            raise ResourceNotFoundError(
                f"Baremetal node with id '{node_id}' not found"
            )

        # Check for duplicate MAC address
        existing = self.store.get("baremetal_ports", address)
        if existing is not None:
            raise DuplicateResourceError(
                f"Baremetal port with address '{address}' already exists"
            )

        now = datetime.now(timezone.utc).isoformat()
        port = BaremetalPort(
            id=str(uuid.uuid4()),
            node_id=node_id,
            address=address,
            status="ACTIVE",
            created_at=now,
        )
        self.store.add("baremetal_ports", address, port)
        return port

    def list_ports(self, node_id: str | None = None) -> list[BaremetalPort]:
        """Return all non-deleted baremetal ports, optionally filtered by node_id.

        Args:
            node_id: If provided, only return ports belonging to this node.
        """
        ports = self.store.list_active("baremetal_ports")
        if node_id is not None:
            ports = [p for p in ports if p.node_id == node_id]
        return ports

    def delete_port(self, address: str) -> None:
        """Soft-delete a baremetal port by MAC address.

        Raises:
            ResourceNotFoundError: If port not found.
        """
        port = self.store.get("baremetal_ports", address)
        if port is None:
            raise ResourceNotFoundError(
                f"Baremetal port with address '{address}' not found"
            )
        self.store.mark_deleted("baremetal_ports", address)

    def set_power_state(self, name: str, target: str) -> BaremetalNode:
        """Change the power state of a baremetal node.

        Valid targets:
            - "power on": when provision_state in {available, active}
            - "power off": when provision_state in {available, active}
            - "rebooting": when power_state is "power on" (results in "power on")

        Args:
            name: The name of the node.
            target: The desired power state target.

        Raises:
            ResourceNotFoundError: If node not found.
            InvalidStateError: If provision_state in {enroll, manageable}
                or if target is invalid for the current state.
        """
        node = self.store.get("baremetal_nodes", name)
        if node is None:
            raise ResourceNotFoundError(f"Baremetal node '{name}' not found")

        # Reject power state changes for nodes in enroll or manageable states
        if node.provision_state in ("enroll", "manageable"):
            raise InvalidStateError(
                f"Cannot change power state while node is in "
                f"provision_state '{node.provision_state}'"
            )

        if target == "power on":
            node.power_state = "power on"
        elif target == "power off":
            node.power_state = "power off"
        elif target == "rebooting":
            if node.power_state != "power on":
                raise InvalidStateError(
                    "Cannot reboot a node that is not powered on"
                )
            # Simulate instant reboot: passes through rebooting, ends at power on
            node.power_state = "power on"
        else:
            raise InvalidStateError(
                f"Invalid power state target: '{target}'"
            )

        node.updated_at = datetime.now(timezone.utc).isoformat()
        return node

    def set_provision_state(self, name: str, target: str) -> BaremetalNode:
        """Transition a node's provision state.

        Valid transitions:
            enroll + "manage" → manageable
            manageable + "provide" → available
            manageable + "clean" → manageable (passes through cleaning)
            available + "active" → active (power_state → "power on")
            active + "deleted" → available (undeploy, power_state → "power off")
            available + "deleted" → soft-delete via store

        Args:
            name: The node name.
            target: The target provision action.

        Returns:
            The updated BaremetalNode.

        Raises:
            ResourceNotFoundError: If node not found.
            InvalidStateError: If the transition is not valid.
        """
        node = self.store.get("baremetal_nodes", name)
        if node is None:
            raise ResourceNotFoundError(
                f"Baremetal node '{name}' not found"
            )

        current_state = node.provision_state

        if current_state == "enroll" and target == "manage":
            node.provision_state = "manageable"
        elif current_state == "manageable" and target == "provide":
            node.provision_state = "available"
        elif current_state == "manageable" and target == "clean":
            # Passes through cleaning, ends up back at manageable
            node.provision_state = "manageable"
        elif current_state == "available" and target == "active":
            node.provision_state = "active"
            node.power_state = "power on"
        elif current_state == "active" and target == "deleted":
            # Undeploy: transition back to available, power off
            node.provision_state = "available"
            node.power_state = "power off"
        elif current_state == "available" and target == "deleted":
            # Soft-delete via store
            node.provision_state = "deleted"
            self.store.mark_deleted("baremetal_nodes", name)
        else:
            raise InvalidStateError(
                f"Invalid provision state transition: "
                f"'{current_state}' + '{target}'"
            )

        node.updated_at = datetime.now(timezone.utc).isoformat()
        return node
