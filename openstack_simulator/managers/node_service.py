"""NodeService: single read/write path for baremetal nodes.

Every read goes through ``sync(now)``, which applies due transitions first.
All reads and writes run under the shared simulator lock. ``ctx`` is
duck-typed: ``project_id``, ``is_admin``, ``now``, ``microversion``.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from .. import messages
from ..exceptions import (
    BadRequest,
    InvalidState,
    NodeLocked,
    NotAuthorized,
    ResourceNotFoundError,
)
from ..sim_config import SimConfig
from ..traits import normalize_trait
from .transitions import ApplyContext, FailureInjector, apply_due, pending_for

_PROJECT_ID_RE = re.compile(r"^[0-9a-zA-Z_-]{1,64}$")
_DEPLOY_VERBS = ("deploy", "active")
_BUSY_STATES = ("active", "deploying")


class NodeService:
    def __init__(
        self,
        store: Any,
        cfg: SimConfig,
        placement: Any,
        failures: FailureInjector | None = None,
        lock: Any = None,
        images: Any = None,
    ) -> None:
        self.store = store
        self.cfg = cfg
        self.placement = placement
        self.failures = failures if failures is not None else FailureInjector()
        self.lock = lock if lock is not None else threading.RLock()
        self.images = images

    # -- helpers -----------------------------------------------------------

    def _apply_ctx(self) -> ApplyContext:
        ports = self.store.baremetal_ports
        return ApplyContext(
            cfg=self.cfg,
            ports=lambda node_id: [
                p for p in list(ports.values()) if p.node_id == node_id
            ],
            servers=self.store.instances,
            flavors=self.store.flavors,
            images=self.images,
            placement=self.placement,
            pending=self.store.pending,
        )

    def _sync_locked(self, now: float) -> list[Any]:
        nodes = self.store.list_active("baremetal_nodes")
        actx = self._apply_ctx()
        for node in nodes:
            pending = self.store.pending.get(node.id)
            if pending is not None:
                apply_due(node, pending, now, self.failures, actx)
        return nodes

    def _find(self, ident: str) -> Any:
        node = self.store.get("baremetal_nodes", ident)
        if node is None:
            for candidate in self.store.list_active("baremetal_nodes"):
                if candidate.id == ident:
                    return candidate
            raise ResourceNotFoundError(f"Baremetal node '{ident}' not found")
        return node

    @staticmethod
    def _require_admin(ctx: Any) -> None:
        if not getattr(ctx, "is_admin", False):
            raise NotAuthorized(messages.admin_required())

    def _write_traits(self, node: Any, traits: list[str]) -> None:
        node.traits = traits
        self.placement.ensure_provider(node)
        self.placement.set_traits(node.id, traits)

    # -- public API --------------------------------------------------------

    def sync(self, now: float) -> list[Any]:
        """Apply all due transitions and return the active nodes."""
        with self.lock:
            return self._sync_locked(now)

    def visible_nodes(self, ctx: Any) -> list[Any]:
        with self.lock:
            nodes = self._sync_locked(ctx.now)
            if ctx.is_admin:
                return list(nodes)
            return [
                n
                for n in nodes
                if n.owner == ctx.project_id or n.lessee == ctx.project_id
            ]

    def provision(self, ctx: Any, ident: str, verb: str) -> Any:
        self._require_admin(ctx)
        with self.lock:
            self._sync_locked(ctx.now)
            node = self._find(ident)
            if verb in _DEPLOY_VERBS and node.lessee and node.lessee != ctx.project_id:
                raise NotAuthorized(messages.not_authorized(node.id))
            if node.target_provision_state is not None:
                raise NodeLocked(messages.node_locked(node.id))
            # plan raises InvalidState / NodeNotProvided, applies maintenance rules
            pending = pending_for(node, verb, self.cfg, ctx.now)
            node.target_provision_state = pending.final_state
            self.store.pending[node.id] = pending
            return node

    def set_maintenance(
        self, ident: str, on: bool, reason: str | None = None
    ) -> Any:
        with self.lock:
            node = self._find(ident)
            node.maintenance = bool(on)
            node.maintenance_reason = reason if on else None
            return node

    def set_owner(self, ctx: Any, ident: str, owner: str | None) -> Any:
        self._require_admin(ctx)
        with self.lock:
            self._sync_locked(ctx.now)
            node = self._find(ident)
            if node.provision_state in _BUSY_STATES:
                raise InvalidState(messages.invalid_state(node.provision_state, node.id))
            node.owner = owner
            return node

    def set_lessee(self, ctx: Any, ident: str, lessee: str | None) -> Any:
        self._require_admin(ctx)
        if lessee is not None and not (
            isinstance(lessee, str) and _PROJECT_ID_RE.match(lessee)
        ):
            raise BadRequest(f"Invalid lessee: {lessee!r}")
        with self.lock:
            self._sync_locked(ctx.now)
            node = self._find(ident)
            if node.provision_state == "active":
                server = self.store.instances.get(node.instance_uuid)
                server_project = getattr(server, "project_id", None)
                if lessee != server_project:
                    raise InvalidState(
                        messages.invalid_state(node.provision_state, node.id)
                    )
            node.lessee = lessee
            return node

    def set_resource_class(self, ident: str, value: str | None) -> Any:
        with self.lock:
            node = self._find(ident)
            node.resource_class = value
            self.placement.ensure_provider(node)
            return node

    def set_protected(self, ident: str, value: bool) -> Any:
        with self.lock:
            node = self._find(ident)
            node.protected = bool(value)
            return node

    def set_target_raid_config(self, ident: str, value: dict | None) -> Any:
        with self.lock:
            node = self._find(ident)
            node.target_raid_config = value
            return node

    def add_trait(self, ident: str, trait: str) -> Any:
        name = normalize_trait(trait)
        with self.lock:
            node = self._find(ident)
            traits = list(node.traits or [])
            if name not in traits:
                traits.append(name)
            self._write_traits(node, traits)
            return node

    def remove_trait(self, ident: str, trait: str) -> Any:
        name = normalize_trait(trait)
        with self.lock:
            node = self._find(ident)
            traits = [t for t in (node.traits or []) if t != name]
            self._write_traits(node, traits)
            return node
