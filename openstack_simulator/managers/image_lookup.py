"""Read-only adapter over ``store.images`` with server-creation defaults.

Image records come from the ``image-create-delete`` spec and may be plain
dicts or objects. Missing attributes fall back to these defaults:

- ``owner`` absent: visible to every project
- ``visibility`` absent: ``public``
- ``hw_architecture`` absent: architecture check skipped
- ``kernel_id`` / ``ramdisk_id`` / ``img_type`` absent: whole-disk image

This module never writes to the store and does not alter the Image API.
"""

from __future__ import annotations

from typing import Any

WHOLE_DISK_TYPES = frozenset({"ami", "raw"})
_OPEN_VISIBILITIES = frozenset({"public", "community"})


def _attr(image: Any, name: str) -> Any:
    if isinstance(image, dict):
        return image.get(name)
    return getattr(image, name, None)


class ImageLookup:
    """Adapter exposing image facts needed by server creation."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def _images(self) -> dict[str, Any]:
        return getattr(self._store, "images", None) or {}

    def get(self, image_id: str | None) -> Any | None:
        """Return the image record, or None if missing or deleted."""
        if not image_id:
            return None
        image = self._images().get(image_id)
        if image is None:
            return None
        if str(_attr(image, "status") or "").lower() == "deleted":
            return None
        return image

    def get_visible(self, image_id: str | None, project_id: str | None) -> Any | None:
        """Return the image only if it exists and is visible to the project."""
        image = self.get(image_id)
        if image is None or not self.is_visible(image, project_id):
            return None
        return image

    @staticmethod
    def visibility(image: Any) -> str:
        value = _attr(image, "visibility")
        return str(value).lower() if value else "public"

    def is_visible(self, image: Any, project_id: str | None) -> bool:
        owner = _attr(image, "owner")
        if not owner:
            return True
        if self.visibility(image) in _OPEN_VISIBILITIES:
            return True
        return owner == project_id

    @staticmethod
    def is_active(image: Any) -> bool:
        return str(_attr(image, "status") or "").lower() == "active"

    @staticmethod
    def architecture(image: Any) -> str | None:
        """Return ``hw_architecture`` or None when the check must be skipped."""
        value = _attr(image, "hw_architecture")
        if value is None:
            props = _attr(image, "properties")
            if isinstance(props, dict):
                value = props.get("hw_architecture")
        return str(value) if value else None

    @staticmethod
    def is_whole_disk(image: Any) -> bool:
        img_type = _attr(image, "img_type")
        if img_type and str(img_type).lower() in WHOLE_DISK_TYPES:
            return True
        return not _attr(image, "kernel_id") and not _attr(image, "ramdisk_id")

    def resolve_kernel_ramdisk(self, image: Any) -> tuple[Any, Any] | None:
        """Return (kernel, ramdisk) records for a partition image.

        Returns None if either cannot be resolved. Whole-disk images need
        neither, so they return (None, None).
        """
        if self.is_whole_disk(image):
            return (None, None)
        kernel = self.get(_attr(image, "kernel_id"))
        ramdisk = self.get(_attr(image, "ramdisk_id"))
        if kernel is None or ramdisk is None:
            return None
        return (kernel, ramdisk)

    def has_resolvable_kernel_ramdisk(self, image: Any) -> bool:
        return self.resolve_kernel_ramdisk(image) is not None
