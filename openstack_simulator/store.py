"""In-memory resource storage for the OpenStack Simulator."""

from __future__ import annotations

from typing import Any

from openstack_simulator.models import (
    BaremetalNode,
    BaremetalPort,
    Bond,
    Flavor,
    Image,
    Instance,
    Network,
    PendingTransition,
    Port,
    Router,
    SecurityGroup,
    Snapshot,
    Subnet,
    Token,
    Volume,
)


class ResourceStore:
    """Central in-memory storage for all simulated resources."""

    def __init__(self) -> None:
        self.instances: dict[str, Instance] = {}
        self.networks: dict[str, Network] = {}
        self.subnets: dict[str, Subnet] = {}
        self.routers: dict[str, Router] = {}
        self.ports: dict[str, Port] = {}
        self.bonds: dict[str, Bond] = {}
        self.volumes: dict[str, Volume] = {}
        self.security_groups: dict[str, SecurityGroup] = {}
        self.tokens: dict[str, Token] = {}
        self.snapshots: list[Snapshot] = []
        self.baremetal_nodes: dict[str, BaremetalNode] = {}
        self.baremetal_ports: dict[str, BaremetalPort] = {}
        self.flavors: dict[str, Flavor] = {}
        self.keypairs: dict[str, Any] = {}
        self.flavor_access: dict[str, set[str]] = {}
        self.pending: dict[str, PendingTransition] = {}
        self.server_groups: dict[str, Any] = {}
        self.images: dict[str, Image] = {}
        self._seed_flavors()

    def _seed_flavors(self) -> None:
        """Seed static m1.* flavors (no resources: extra spec, legacy path)."""
        for name, ram, vcpus, disk in (
            ("m1.tiny", 512, 1, 1),
            ("m1.small", 2048, 1, 20),
            ("m1.medium", 4096, 2, 40),
            ("m1.large", 8192, 4, 80),
            ("m1.xlarge", 16384, 8, 160),
        ):
            self.flavors[name] = Flavor(
                id=name, name=name, vcpus=vcpus, ram=ram, disk=disk
            )

    def add(self, resource_type: str, name: str, resource: Any) -> None:
        """Store a resource by type and name."""
        store = getattr(self, resource_type)
        store[name] = resource

    def get(self, resource_type: str, name: str) -> Any | None:
        """Retrieve a non-deleted resource by type and name.

        Returns None if not found or if the resource status is DELETED.
        """
        store = getattr(self, resource_type)
        resource = store.get(name)
        if resource is None:
            return None
        if hasattr(resource, "status") and resource.status == "DELETED":
            return None
        return resource

    def list_active(self, resource_type: str) -> list[Any]:
        """Return all non-deleted resources of the given type."""
        store = getattr(self, resource_type)
        return [
            resource
            for resource in store.values()
            if not hasattr(resource, "status") or resource.status != "DELETED"
        ]

    def mark_deleted(self, resource_type: str, name: str) -> None:
        """Set a resource's status to DELETED."""
        store = getattr(self, resource_type)
        resource = store.get(name)
        if resource is not None:
            resource.status = "DELETED"

    def remove(self, resource_type: str, key: str) -> bool:
        """Remove a resource entry. Return True if it existed."""
        store = getattr(self, resource_type)
        if key in store:
            del store[key]
            return True
        return False

    def clear(self) -> None:
        """Empty every collection in place, keeping the store object identity.

        The static m1.* flavors are seeded again so the store returns to its
        initial state.
        """
        for value in vars(self).values():
            if isinstance(value, (dict, list)):
                value.clear()
        self._seed_flavors()

    def count_active(self, resource_type: str) -> int:
        """Count non-deleted resources of the given type."""
        store = getattr(self, resource_type)
        return sum(
            1
            for resource in store.values()
            if not hasattr(resource, "status") or resource.status != "DELETED"
        )
