"""Simulated Neutron security group manager for the OpenStack Simulator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
)
from openstack_simulator.models import Rule, SecurityGroup, _generate_id, _now_timestamp

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


class SecurityGroupManager:
    """Simulated Neutron security group manager."""

    def __init__(self, store: ResourceStore, limiter: ResourceLimiter) -> None:
        self.store = store
        self.limiter = limiter

    def create(self, name: str, description: str) -> SecurityGroup:
        """Create a new security group.

        Raises:
            ResourceLimitExceededError: If max security groups reached.
            DuplicateResourceError: If name already exists (non-deleted).
        """
        self.limiter.check("security_groups", self.store)

        existing = self.store.get("security_groups", name)
        if existing is not None:
            raise DuplicateResourceError(
                f"Security group '{name}' already exists"
            )

        sg = SecurityGroup(
            id=_generate_id(),
            name=name,
            description=description,
            rules=[],
            created_at=_now_timestamp(),
            status="ACTIVE",
        )
        self.store.add("security_groups", name, sg)
        return sg

    def get(self, name: str) -> SecurityGroup | None:
        """Get a security group by name. Returns None if not found."""
        return self.store.get("security_groups", name)

    def add_rule(
        self,
        sg_name: str,
        protocol: str,
        port_range: str,
        direction: str,
        remote_ip_prefix: str,
    ) -> Rule:
        """Add a rule to a security group.

        Raises:
            ResourceNotFoundError: If security group not found.
        """
        sg = self.store.get("security_groups", sg_name)
        if sg is None:
            raise ResourceNotFoundError(
                f"Security group '{sg_name}' not found"
            )

        rule = Rule(
            id=_generate_id(),
            security_group_id=sg.id,
            protocol=protocol,
            port_range=port_range,
            direction=direction,
            remote_ip_prefix=remote_ip_prefix,
        )
        sg.rules.append(rule)
        return rule

    def delete_rule(self, rule_id: str) -> None:
        """Remove a rule by its UUID.

        Raises:
            ResourceNotFoundError: If rule not found.
        """
        for sg in self.store.security_groups.values():
            for rule in sg.rules:
                if rule.id == rule_id:
                    sg.rules.remove(rule)
                    return

        raise ResourceNotFoundError(f"Rule '{rule_id}' not found")

    def delete(self, name: str) -> None:
        """Soft-delete a security group.

        Raises:
            ResourceNotFoundError: If security group not found.
        """
        sg = self.store.get("security_groups", name)
        if sg is None:
            raise ResourceNotFoundError(
                f"Security group '{name}' not found"
            )

        self.store.mark_deleted("security_groups", name)

    def list(self) -> list[SecurityGroup]:
        """Return all non-deleted security groups."""
        return self.store.list_active("security_groups")
