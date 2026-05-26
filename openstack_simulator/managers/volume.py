"""Simulated Cinder volume manager for the OpenStack Simulator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidStateError,
    ResourceNotFoundError,
)
from openstack_simulator.models import Snapshot, Volume, _generate_id, _now_timestamp

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


class VolumeManager:
    """Simulated Cinder storage manager."""

    def __init__(self, store: ResourceStore, limiter: ResourceLimiter) -> None:
        self.store = store
        self.limiter = limiter

    def create(self, name: str, size: int) -> Volume:
        """Create a new volume.

        Raises:
            ResourceLimitExceededError: If max volumes reached.
            DuplicateResourceError: If name already exists (non-deleted).
        """
        self.limiter.check("volumes", self.store)

        existing = self.store.get("volumes", name)
        if existing is not None:
            raise DuplicateResourceError(f"Volume '{name}' already exists")

        volume = Volume(
            id=_generate_id(),
            name=name,
            size=size,
            status="available",
            created_at=_now_timestamp(),
            attached_to=None,
        )
        self.store.add("volumes", name, volume)
        return volume

    def get(self, name: str) -> Volume | None:
        """Get a volume by name. Returns None if not found."""
        return self.store.get("volumes", name)

    def attach(self, volume_name: str, instance_name: str) -> Volume:
        """Attach a volume to an instance.

        Raises:
            ResourceNotFoundError: If volume or instance not found.
            InvalidStateError: If volume is already in-use.
        """
        volume = self.store.get("volumes", volume_name)
        if volume is None:
            raise ResourceNotFoundError(f"Volume '{volume_name}' not found")

        instance = self.store.get("instances", instance_name)
        if instance is None:
            raise ResourceNotFoundError(f"Instance '{instance_name}' not found")

        if volume.status == "in-use":
            raise InvalidStateError(
                f"Volume '{volume_name}' is already in-use"
            )

        volume.status = "in-use"
        volume.attached_to = instance_name
        return volume

    def snapshot(self, name: str, snapshot_name: str) -> Snapshot:
        """Create a snapshot of a volume.

        Raises:
            ResourceNotFoundError: If volume not found.
        """
        volume = self.store.get("volumes", name)
        if volume is None:
            raise ResourceNotFoundError(f"Volume '{name}' not found")

        snap = Snapshot(
            id=_generate_id(),
            name=snapshot_name,
            source_id=volume.id,
            source_type="volume",
            created_at=_now_timestamp(),
        )
        self.store.snapshots.append(snap)
        return snap

    def delete(self, name: str) -> None:
        """Soft-delete a volume.

        Raises:
            ResourceNotFoundError: If volume not found.
            InvalidStateError: If volume is in-use.
        """
        volume = self.store.get("volumes", name)
        if volume is None:
            raise ResourceNotFoundError(f"Volume '{name}' not found")

        if volume.status == "in-use":
            raise InvalidStateError(
                f"Volume '{name}' is in-use and cannot be deleted"
            )

        self.store.mark_deleted("volumes", name)

    def list(self) -> list[Volume]:
        """Return all non-deleted volumes."""
        return self.store.list_active("volumes")
