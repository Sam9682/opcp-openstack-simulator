"""Simulated Placement service: one resource provider per baremetal node."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


@dataclass
class Inventory:
    total: int = 1
    reserved: int = 0
    allocation_ratio: float = 1.0


@dataclass
class Provider:
    uuid: str
    parent: str | None = None
    inventory: dict[str, Inventory] = field(default_factory=dict)
    traits: frozenset[str] = frozenset()
    allocations: dict[str, str] = field(default_factory=dict)  # consumer -> rc


@dataclass(frozen=True)
class ProviderView:
    """Immutable copy of a provider, safe to hand to the pure scheduler."""

    uuid: str
    parent: str | None
    inventory: Mapping[str, Inventory]
    traits: frozenset[str]
    allocations: Mapping[str, str]


class PlacementService:
    """Providers, inventory, allocations and traits.

    All mutation and snapshotting happens under ``lock`` (``Simulator.lock``).
    """

    def __init__(self, lock: Any = None) -> None:
        self._lock = lock if lock is not None else threading.RLock()
        self._providers: dict[str, Provider] = {}

    def ensure_provider(self, node: Any) -> Provider:
        """Create the provider for ``node`` if missing; keep inventory in step
        with the node resource class. Existing traits are left untouched."""
        with self._lock:
            provider = self._providers.get(node.id)
            if provider is None:
                provider = Provider(
                    uuid=node.id, traits=frozenset(node.traits or ())
                )
                self._providers[node.id] = provider
            rc = node.resource_class
            if rc and rc not in provider.inventory:
                provider.inventory[rc] = Inventory(1, 0, 1.0)
            return provider

    def remove_provider(self, provider_id: str) -> None:
        with self._lock:
            self._providers.pop(provider_id, None)

    def snapshot(self) -> Mapping[str, ProviderView]:
        with self._lock:
            return MappingProxyType(
                {
                    pid: ProviderView(
                        uuid=p.uuid,
                        parent=p.parent,
                        inventory=MappingProxyType(
                            {
                                k: Inventory(
                                    v.total, v.reserved, v.allocation_ratio
                                )
                                for k, v in p.inventory.items()
                            }
                        ),
                        traits=p.traits,
                        allocations=MappingProxyType(dict(p.allocations)),
                    )
                    for pid, p in self._providers.items()
                }
            )

    def claim(self, provider_id: str, consumer_id: str, rc: str) -> bool:
        """Compare-and-set: succeed only if the provider exists, has inventory
        for ``rc`` and holds no allocation."""
        with self._lock:
            provider = self._providers.get(provider_id)
            if provider is None or rc not in provider.inventory:
                return False
            if provider.allocations:
                return False
            provider.allocations[consumer_id] = rc
            return True

    def release(self, consumer_id: str) -> bool:
        """Remove the allocation of ``consumer_id``. True the first time only."""
        with self._lock:
            released = False
            for provider in self._providers.values():
                if provider.allocations.pop(consumer_id, None) is not None:
                    released = True
            return released

    def set_traits(self, provider_id: str, traits: Iterable[str]) -> None:
        with self._lock:
            provider = self._providers.get(provider_id)
            if provider is not None:
                provider.traits = frozenset(traits)

    def resync_traits(self, nodes: Iterable[Any]) -> None:
        """Make provider traits equal node traits (node is source of truth)."""
        with self._lock:
            for node in nodes:
                self.set_traits(node.id, node.traits or ())
