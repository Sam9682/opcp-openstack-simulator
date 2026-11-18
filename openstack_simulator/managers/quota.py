"""Per-project Quota checks (server-creation-rules, Requirement 18)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from openstack_simulator import messages
from openstack_simulator.exceptions import QuotaExceeded

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.models import Flavor
    from openstack_simulator.sim_config import SimConfig
    from openstack_simulator.store import ResourceStore

QUOTA_RESOURCES = (
    "instances",
    "cores",
    "ram",
    "key_pairs",
    "server_groups",
    "server_group_members",
)


class QuotaManager:
    """Quota limits, usage and creation checks for a project."""

    def __init__(
        self,
        store: ResourceStore,
        limiter: ResourceLimiter,
        config: Optional[SimConfig] = None,
    ) -> None:
        self.store = store
        self.limiter = limiter
        self.config = config

    def _enforced(self) -> bool:
        return True if self.config is None else self.config.guards.enforce_quota

    def limit(self, project: str, resource: str) -> int | None:
        """Quota value for ``resource``; None means no limit."""
        return self.limiter.project_limit(resource)

    def _live_servers(self, project: str):
        return [
            s
            for s in self.store.instances.values()
            if s.status != "DELETED" and s.project_id == project
        ]

    def usage(self, project: str, resource: str) -> int:
        if resource == "instances":
            return len(self._live_servers(project))
        if resource == "cores":
            return sum(s.flavor_vcpus or 0 for s in self._live_servers(project))
        if resource == "ram":
            return sum(s.flavor_ram or 0 for s in self._live_servers(project))
        if resource == "key_pairs":
            return len(self.store.keypairs)
        groups = getattr(self.store, "server_groups", {})
        if resource == "server_groups":
            return len(groups)
        if resource == "server_group_members":
            return sum(
                len(g.get("members", []) if isinstance(g, dict) else getattr(g, "members", []))
                for g in groups.values()
            )
        return 0

    def check_create(self, project: str, flavor: Flavor) -> None:
        """Raise QuotaExceeded for the first Quota the new server would exceed.

        The global ``instances`` limit is the same value as the project
        ``instances`` Quota, so it is checked once here and never twice.
        """
        if not self._enforced():
            return
        requested = {"instances": 1, "cores": flavor.vcpus, "ram": flavor.ram}
        for resource, n in requested.items():
            limit = self.limit(project, resource)
            if limit is None:
                continue
            used = self.usage(project, resource)
            if used + n > limit:
                raise QuotaExceeded(messages.quota_exceeded(resource, n, used, limit))

    def snapshot(self, project: str) -> dict[str, tuple[int, int | None]]:
        """Map each Quota resource to ``(used, limit)``."""
        return {
            r: (self.usage(project, r), self.limit(project, r))
            for r in QUOTA_RESOURCES
        }
