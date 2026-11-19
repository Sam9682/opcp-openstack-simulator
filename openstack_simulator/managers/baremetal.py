"""Simulated Ironic baremetal manager for the OpenStack Simulator."""

from __future__ import annotations

import copy
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidPatchError,
    InvalidStateError,
    ResourceNotFoundError,
)
from openstack_simulator.clock import Clock
from openstack_simulator.exceptions import SimError
from openstack_simulator.managers.transitions import apply_due, pending_for
from openstack_simulator.models import BaremetalNode, BaremetalPort

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


PATCH_OPS = {"add", "replace", "remove"}
NESTED_DICT_ROOTS = {"properties", "driver_info"}
SCALAR_PATHS = {
    "/driver": "driver",
    "/memory_mb": "memory_mb",
    "/cpus": "cpus",
    "/local_gb": "local_gb",
    "/cpu_arch": "cpu_arch",
}


class BaremetalManager:
    """Simulated Ironic baremetal manager."""

    def __init__(
        self,
        store: ResourceStore,
        limiter: ResourceLimiter,
        node_service: Any = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.limiter = limiter
        # Optional: when set, reads sync due transitions and legacy provision
        # targets run through the shared plan/apply code.
        self.node_service = node_service
        self.clock = clock if clock is not None else Clock()

    def _sync(self) -> float:
        """Apply due transitions (if a NodeService is wired); return now."""
        now = self.clock.now()
        if self.node_service is not None:
            self.node_service.sync(now)
        return now

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
        uuid: str | None = None,
    ) -> BaremetalNode:
        """Create a new baremetal node.

        Args:
            uuid: Optional node UUID. Stored in canonical lowercase form.
                When omitted a random UUID v4 is generated.

        UUID reuse decision: duplicates are checked against active nodes
        only, so the UUID of a soft-deleted node may be reused (same rule
        as names).

        Raises:
            ResourceLimitExceededError: If max_baremetal_nodes reached.
            DuplicateResourceError: If name already exists (non-deleted), or
                an active node already has the given UUID.
            ValueError: If uuid is given and is not a valid UUID.
        """
        node_id: str | None = None
        if uuid is not None:
            if not isinstance(uuid, str):
                raise ValueError(f"Invalid node UUID: {uuid!r}")
            node_id = str(uuid_lib.UUID(uuid))

        self.limiter.check("baremetal_nodes", self.store)

        existing = self.store.get("baremetal_nodes", name)
        if existing is not None:
            raise DuplicateResourceError(
                f"Baremetal node '{name}' already exists"
            )

        if node_id is None:
            node_id = str(uuid_lib.uuid4())
        elif any(n.id == node_id for n in self.store.list_active("baremetal_nodes")):
            raise DuplicateResourceError(
                f"Baremetal node with UUID '{node_id}' already exists"
            )

        now = datetime.now(timezone.utc).isoformat()
        node = BaremetalNode(
            id=node_id,
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
        placement = getattr(self.node_service, "placement", None)
        if placement is not None:
            placement.ensure_provider(node)
        return node

    def get_node(self, name: str) -> BaremetalNode | None:
        """Get a baremetal node by name. Returns None if not found."""
        self._sync()
        return self.store.get("baremetal_nodes", name)

    def list_nodes(self) -> list[BaremetalNode]:
        """Return all non-deleted baremetal nodes."""
        self._sync()
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
        self._sync()
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

    @staticmethod
    def _split_patch_path(path: str) -> list[str]:
        """Split a JSON Pointer into decoded segments."""
        if not path.startswith("/"):
            raise InvalidPatchError(f"Unsupported patch path '{path}'")
        return [
            seg.replace("~1", "/").replace("~0", "~")
            for seg in path[1:].split("/")
        ]

    @staticmethod
    def _patch_nested(
        root: dict, keys: list[str], op: str, value, path: str
    ) -> None:
        """Apply add/replace/remove at a nested location inside ``root``."""
        if any(k == "" for k in keys):
            raise InvalidPatchError(f"Empty key in patch path '{path}'")
        target = root
        for key in keys[:-1]:
            nxt = target.get(key)
            if nxt is None and key not in target:
                if op != "add":
                    raise InvalidPatchError(
                        f"Path '{path}' does not exist"
                    )
                nxt = {}
                target[key] = nxt
            if not isinstance(nxt, dict):
                raise InvalidPatchError(
                    f"Path '{path}' traverses a non-dictionary value"
                )
            target = nxt
        last = keys[-1]
        if op == "remove":
            if last not in target:
                raise InvalidPatchError(f"Cannot remove missing key '{path}'")
            del target[last]
        else:
            target[last] = copy.deepcopy(value)

    def patch_node(self, node_name: str, operations: list) -> BaremetalNode:
        """Apply a JSON Patch atomically to a node.

        Raises:
            ResourceNotFoundError: If node not found.
            InvalidPatchError: Bad op, unsupported path, malformed operation,
                or removal of a missing key.
            DuplicateResourceError: If a rename collides with another node.
        """
        self._sync()
        node = self.store.get("baremetal_nodes", node_name)
        if node is None:
            raise ResourceNotFoundError(
                f"Baremetal node '{node_name}' not found"
            )
        if not isinstance(operations, list):
            raise InvalidPatchError("Patch body must be a list of operations")

        work = {
            "name": node.name,
            "driver": node.driver,
            "memory_mb": node.memory_mb,
            "cpus": node.cpus,
            "local_gb": node.local_gb,
            "cpu_arch": node.cpu_arch,
            "properties": copy.deepcopy(node.properties),
            "driver_info": copy.deepcopy(node.driver_info),
            "extra": copy.deepcopy(node.extra),
        }

        for operation in operations:
            if not isinstance(operation, dict):
                raise InvalidPatchError("Patch operation must be an object")
            op = operation.get("op")
            path = operation.get("path")
            if not isinstance(op, str) or not isinstance(path, str):
                raise InvalidPatchError(
                    "Patch operation requires string 'op' and 'path'"
                )
            if op not in PATCH_OPS:
                raise InvalidPatchError(f"Unsupported patch op '{op}'")
            if op != "remove" and "value" not in operation:
                raise InvalidPatchError(
                    f"Patch op '{op}' on '{path}' requires 'value'"
                )
            value = operation.get("value")

            segments = self._split_patch_path(path)
            root = segments[0]

            if path in SCALAR_PATHS:
                if op == "remove":
                    raise InvalidPatchError(f"Cannot remove '{path}'")
                work[SCALAR_PATHS[path]] = value
            elif path == "/name":
                if op == "remove":
                    raise InvalidPatchError("Cannot remove '/name'")
                if not isinstance(value, str) or not value:
                    raise InvalidPatchError(
                        "'/name' value must be a non-empty string"
                    )
                work["name"] = value
            elif root in NESTED_DICT_ROOTS and len(segments) == 2:
                self._patch_nested(work[root], segments[1:], op, value, path)
            elif root == "extra" and len(segments) == 1:
                if op == "remove":
                    raise InvalidPatchError("Cannot remove '/extra'")
                if not isinstance(value, dict):
                    raise InvalidPatchError(
                        "'/extra' value must be a dictionary"
                    )
                work["extra"] = copy.deepcopy(value)
            elif root == "extra":
                self._patch_nested(work["extra"], segments[1:], op, value, path)
            else:
                raise InvalidPatchError(f"Unsupported patch path '{path}'")

        new_name = work["name"]
        renamed = new_name != node_name
        if renamed and self.store.get("baremetal_nodes", new_name) is not None:
            raise DuplicateResourceError(
                f"Baremetal node '{new_name}' already exists"
            )

        for key, val in work.items():
            setattr(node, key, val)
        node.updated_at = datetime.now(timezone.utc).isoformat()

        if renamed:
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
        placement = getattr(self.node_service, "placement", None)
        if placement is not None:
            placement.remove_provider(node.id)

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
        self._sync()

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
            id=str(uuid_lib.uuid4()),
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
        self._sync()
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
        self._sync()
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
        now = self._sync()
        node = self.store.get("baremetal_nodes", name)
        if node is None:
            raise ResourceNotFoundError(
                f"Baremetal node '{name}' not found"
            )

        if self.node_service is not None:
            return self._legacy_provision(node, name, target, now)

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
            placement = getattr(self.node_service, "placement", None)
            if placement is not None:
                placement.remove_provider(node.id)
        else:
            raise InvalidStateError(
                f"Invalid provision state transition: "
                f"'{current_state}' + '{target}'"
            )

        node.updated_at = datetime.now(timezone.utc).isoformat()
        return node

    def _legacy_provision(
        self, node: BaremetalNode, name: str, target: str, now: float
    ) -> BaremetalNode:
        """Run a legacy target through the shared plan/apply code."""
        svc = self.node_service
        state = node.provision_state
        invalid = InvalidStateError(
            f"Invalid provision state transition: '{state}' + '{target}'"
        )
        if node.target_provision_state is not None:
            raise invalid

        verb = None
        if target in ("manage", "provide"):
            verb = target
        elif target == "clean" and state == "manageable":
            verb = "inspect"  # manageable -> ... -> manageable
        elif target == "deleted" and state == "active":
            verb = "undeploy"
        elif target == "active" and state == "available":
            node.provision_state = "active"
            node.power_state = "power on"
        elif target == "deleted" and state == "available":
            node.provision_state = "deleted"
            self.store.mark_deleted("baremetal_nodes", name)
            placement = getattr(self.node_service, "placement", None)
            if placement is not None:
                placement.remove_provider(node.id)
        else:
            raise invalid

        if verb is not None:
            try:
                pending = pending_for(node, verb, svc.cfg, now)
            except SimError as exc:
                raise InvalidStateError(str(exc)) from exc
            node.target_provision_state = pending.final_state
            self.store.pending[node.id] = pending
            if verb == "undeploy":
                node.power_state = "power off"
            with svc.lock:
                apply_due(node, pending, now, svc.failures, svc._apply_ctx())

        node.updated_at = datetime.now(timezone.utc).isoformat()
        return node
