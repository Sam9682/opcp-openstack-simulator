"""Resource limit enforcement for the OpenStack Simulator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openstack_simulator.exceptions import ResourceLimitExceededError

if TYPE_CHECKING:
    from openstack_simulator.store import ResourceStore


class ResourceLimiter:
    """Enforces maximum resource counts per type."""

    def __init__(self, limits: dict[str, int]) -> None:
        """
        Args:
            limits: Mapping of resource type to maximum count.
                    e.g. {"instances": 3, "networks": 2, "volumes": 3, "security_groups": 5}
        """
        self.limits = limits

    def check(self, resource_type: str, store: ResourceStore) -> None:
        """Raise ResourceLimitExceededError if the active count equals or exceeds the limit.

        If no limit is configured for the given resource_type, the check passes.
        """
        limit = self.limits.get(resource_type)
        if limit is None:
            return
        if store.count_active(resource_type) >= limit:
            raise ResourceLimitExceededError(
                f"{resource_type} limit ({limit}) reached"
            )

    def get_limit(self, resource_type: str) -> int:
        """Return the configured limit for a resource type, or 0 if not configured."""
        return self.limits.get(resource_type, 0)
