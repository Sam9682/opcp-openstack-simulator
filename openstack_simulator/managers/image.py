"""Simulated Glance image manager (metadata only) for the OpenStack Simulator."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
)
from openstack_simulator.models import Image, _generate_id, _now_timestamp

if TYPE_CHECKING:
    from openstack_simulator.store import ResourceStore


# (image_id, name) pairs seeded at Simulator start and reset.
PREDEFINED_IMAGES: tuple[tuple[str, str], ...] = (
    ("c9d1b60e-42f5-490f-b6f6-93411c171905", "CentOS 9 OPCP"),
    ("ae8e057f-ef2d-40fc-898c-c112e20ce1e3", "Debian 12 LVM OPCP"),
    ("52870a44-372e-44d5-b767-cd4fdea005cd", "Debian 13 Cloud VM"),
    ("ad4929ea-f0be-459f-8f38-e15b982f52a7", "Parrot-Security"),
    ("d1631dd4-a556-45fb-81c0-b67ba3f92c81", "Proxmox-OPCP"),
    ("1bc89c61-33e4-463a-bd42-6240a096f7fb", "Proxmox-SG"),
    ("0273e687-a54c-49d0-8f2e-29d009e55886", "harverster1.8.1"),
    ("dca50fba-1db3-4abd-913a-0783e4e092c5", "ironic-agent.initramfs"),
    ("0beb46c1-232a-4ff3-abaf-e857593790fa", "ironic-agent.kernel"),
    ("c7770ed8-cb60-4974-9b07-78cffff8bb97", "proxmox-ve-9.2"),
    ("4e9b0922-50fc-4345-a790-0e131cf2247d", "tj-harvester_1-7-1"),
)


def _normalize_uuid(value: object) -> str:
    """Return the canonical lowercase hyphenated UUID, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError(f"Invalid image id '{value}': must be a UUID string")
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"Invalid image id '{value}': not a valid UUID") from None
    if canonical != value.lower():
        raise ValueError(
            f"Invalid image id '{value}': must be in canonical hyphenated form"
        )
    return canonical


class ImageManager:
    """Simulated Glance image manager. Images are keyed by ID."""

    def __init__(self, store: ResourceStore) -> None:
        self.store = store

    def create(
        self,
        name: str | None = None,
        image_id: str | None = None,
        **attrs,
    ) -> Image:
        """Create an image (immediately active).

        Raises:
            ValueError: If image_id is not a canonical UUID.
            DuplicateResourceError: If image_id is already in use.
        """
        if image_id is None:
            image_id = _generate_id()
        else:
            image_id = _normalize_uuid(image_id)

        if image_id in self.store.images:
            raise DuplicateResourceError(f"Image '{image_id}' already exists")

        now = _now_timestamp()
        image = Image(
            id=image_id,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
            **attrs,
        )
        self.store.add("images", image_id, image)
        return image

    def get(self, image_id: str) -> Image | None:
        """Get an image by ID. Returns None if not found."""
        return self.store.images.get(image_id)

    def list(
        self, name: str | None = None, status: str | None = None
    ) -> list[Image]:
        """List images in insertion order, filtered by exact name and status."""
        return [
            image
            for image in self.store.images.values()
            if (name is None or image.name == name)
            and (status is None or image.status == status)
        ]

    def delete(self, image_id: str) -> None:
        """Hard-delete an image.

        Raises:
            ResourceNotFoundError: If the image does not exist.
        """
        if not self.store.remove("images", image_id):
            raise ResourceNotFoundError(f"Image '{image_id}' not found")

    def seed_predefined(self) -> None:
        """Add the predefined images to the store."""
        now = _now_timestamp()
        for image_id, name in PREDEFINED_IMAGES:
            self.store.add(
                "images",
                image_id,
                Image(
                    id=image_id,
                    name=name,
                    status="active",
                    visibility="public",
                    disk_format="qcow2",
                    container_format="bare",
                    created_at=now,
                    updated_at=now,
                ),
            )
