"""Simulated Nova compute manager for the OpenStack Simulator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
)
from openstack_simulator.models import Instance, Snapshot, _generate_id, _now_timestamp

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


class ComputeManager:
    """Simulated Nova compute manager."""

    def __init__(self, store: ResourceStore, limiter: ResourceLimiter) -> None:
        self.store = store
        self.limiter = limiter

    def create(self, name: str, flavor: str, image: str) -> Instance:
        """Create a new compute instance.

        Raises:
            ResourceLimitExceededError: If max_instances reached.
            DuplicateResourceError: If name already exists (non-deleted).
        """
        self.limiter.check("instances", self.store)

        existing = self.store.get("instances", name)
        if existing is not None:
            raise DuplicateResourceError(f"Instance '{name}' already exists")

        instance = Instance(
            id=_generate_id(),
            name=name,
            flavor=flavor,
            image=image,
            status="ACTIVE",
            created_at=_now_timestamp(),
        )
        self.store.add("instances", name, instance)
        return instance

    def get(self, name: str) -> Instance | None:
        """Get an instance by name. Returns None if not found."""
        return self.store.get("instances", name)

    def resize(self, name: str, flavor: str) -> Instance:
        """Resize an instance to a new flavor.

        Raises:
            ResourceNotFoundError: If instance not found.
        """
        instance = self.store.get("instances", name)
        if instance is None:
            raise ResourceNotFoundError(f"Instance '{name}' not found")

        instance.flavor = flavor
        instance.status = "ACTIVE"
        return instance

    def snapshot(self, name: str, snapshot_name: str) -> Snapshot:
        """Create a snapshot of an instance.

        Raises:
            ResourceNotFoundError: If instance not found.
        """
        instance = self.store.get("instances", name)
        if instance is None:
            raise ResourceNotFoundError(f"Instance '{name}' not found")

        snap = Snapshot(
            id=_generate_id(),
            name=snapshot_name,
            source_id=instance.id,
            source_type="instance",
            created_at=_now_timestamp(),
        )
        self.store.snapshots.append(snap)
        return snap

    def delete(self, name: str) -> None:
        """Soft-delete an instance.

        Raises:
            ResourceNotFoundError: If instance not found.
        """
        instance = self.store.get("instances", name)
        if instance is None:
            raise ResourceNotFoundError(f"Instance '{name}' not found")

        self.store.mark_deleted("instances", name)

    def list(self) -> list[Instance]:
        """Return all non-deleted instances."""
        return self.store.list_active("instances")
