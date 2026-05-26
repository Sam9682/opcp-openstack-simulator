"""Simulated Neutron networking manager for the OpenStack Simulator."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
)
from openstack_simulator.models import (
    Bond,
    Network,
    Port,
    Router,
    Subnet,
    _generate_id,
    _now_timestamp,
)

if TYPE_CHECKING:
    from openstack_simulator.limiter import ResourceLimiter
    from openstack_simulator.store import ResourceStore


class NetworkManager:
    """Simulated Neutron networking manager."""

    def __init__(self, store: ResourceStore, limiter: ResourceLimiter) -> None:
        self.store = store
        self.limiter = limiter

    def create(self, name: str) -> Network:
        """Create a new network.

        Raises:
            ResourceLimitExceededError: If max_networks reached.
            DuplicateResourceError: If name already exists (non-deleted).
        """
        self.limiter.check("networks", self.store)

        existing = self.store.get("networks", name)
        if existing is not None:
            raise DuplicateResourceError(f"Network '{name}' already exists")

        network = Network(
            id=_generate_id(),
            name=name,
            status="ACTIVE",
            created_at=_now_timestamp(),
            subnet_ids=[],
        )
        self.store.add("networks", name, network)
        return network

    def get(self, name: str) -> Network | None:
        """Get a network by name. Returns None if not found."""
        return self.store.get("networks", name)

    def create_subnet(
        self, network_name: str, name: str, cidr: str, gateway: str
    ) -> Subnet:
        """Create a subnet on an existing network.

        Raises:
            ResourceNotFoundError: If the network does not exist.
        """
        network = self.store.get("networks", network_name)
        if network is None:
            raise ResourceNotFoundError(f"Network '{network_name}' not found")

        subnet = Subnet(
            id=_generate_id(),
            name=name,
            network_id=network.id,
            cidr=cidr,
            gateway=gateway,
        )
        self.store.add("subnets", name, subnet)
        network.subnet_ids.append(subnet.id)
        return subnet

    def create_router(self, name: str) -> Router:
        """Create a new router.

        Returns the created Router with status ACTIVE.
        """
        router = Router(
            id=_generate_id(),
            name=name,
            status="ACTIVE",
            subnet_ids=[],
        )
        self.store.add("routers", name, router)
        return router

    def add_router_interface(self, router_name: str, subnet_id: str) -> None:
        """Add a subnet interface to a router.

        Raises:
            ResourceNotFoundError: If the router or subnet is not found.
        """
        router = self.store.get("routers", router_name)
        if router is None:
            raise ResourceNotFoundError(f"Router '{router_name}' not found")

        # Find subnet by ID across all stored subnets
        subnet_found = False
        for subnet in self.store.subnets.values():
            if subnet.id == subnet_id:
                subnet_found = True
                break

        if not subnet_found:
            raise ResourceNotFoundError(f"Subnet '{subnet_id}' not found")

        router.subnet_ids.append(subnet_id)

    def create_port(self, network_name: str, name: str) -> Port:
        """Create a port on an existing network.

        Raises:
            ResourceNotFoundError: If the network does not exist.
        """
        network = self.store.get("networks", network_name)
        if network is None:
            raise ResourceNotFoundError(f"Network '{network_name}' not found")

        mac_address = "fa:16:3e:%02x:%02x:%02x" % (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255),
        )

        port = Port(
            id=_generate_id(),
            name=name,
            network_id=network.id,
            mac_address=mac_address,
            status="ACTIVE",
        )
        self.store.add("ports", name, port)
        return port

    def create_bond(self, name: str, port_names: list[str], bond_mode: str) -> Bond:
        """Create a bond from existing ports.

        Raises:
            ResourceNotFoundError: If any port in port_names is not found.
        """
        port_ids: list[str] = []
        for port_name in port_names:
            port = self.store.get("ports", port_name)
            if port is None:
                raise ResourceNotFoundError(f"Port '{port_name}' not found")
            port_ids.append(port.id)

        bond = Bond(
            id=_generate_id(),
            name=name,
            port_ids=port_ids,
            bond_mode=bond_mode,
            status="ACTIVE",
        )
        self.store.add("bonds", name, bond)
        return bond

    def delete(self, name: str) -> None:
        """Soft-delete a network.

        Raises:
            ResourceNotFoundError: If the network does not exist.
        """
        network = self.store.get("networks", name)
        if network is None:
            raise ResourceNotFoundError(f"Network '{name}' not found")

        self.store.mark_deleted("networks", name)

    def list(self) -> list[Network]:
        """Return all non-deleted networks."""
        return self.store.list_active("networks")
