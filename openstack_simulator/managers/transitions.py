"""Ironic node state machine: planning, lazy application and deploy preflight.

``plan`` and ``deploy_preflight`` are pure. ``apply_due`` mutates the node,
the server and the placement allocation. Callers hold ``Simulator.lock``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional

from .. import messages
from ..exceptions import InvalidState, NodeNotProvided
from ..models import PendingTransition, Step, _now_timestamp, node_capacity
from ..sim_config import SimConfig

# (provision_state, verb) -> ordered list of states to pass through.
STATE_MACHINE_TABLE: dict[tuple[str, str], list[str]] = {
    ("enroll", "manage"): ["verifying", "manageable"],  # T1
    ("manageable", "provide"): ["cleaning", "available"],  # T2
    ("available", "clean"): ["cleaning", "available"],  # T6
    ("manageable", "inspect"): ["inspecting", "manageable"],  # T9
    ("deploy failed", "clean"): ["cleaning", "available"],  # T10
    ("clean failed", "clean"): ["cleaning", "available"],  # T10
    ("active", "undeploy"): ["deleting", "cleaning", "available"],  # T5
}

# Delay (timing name, None = 0 s) before each step, relative to the previous
# step (or to ``now`` for the first one). Aligned with STATE_MACHINE_TABLE.
_STEP_DELAYS: dict[tuple[str, str], list[Optional[str]]] = {
    ("enroll", "manage"): ["enroll_to_verifying", "verifying_to_manageable"],
    ("manageable", "provide"): [None, "cleaning"],
    ("available", "clean"): [None, "cleaning"],
    ("manageable", "inspect"): [None, "inspect"],
    ("deploy failed", "clean"): [None, "cleaning"],
    ("clean failed", "clean"): [None, "cleaning"],
    ("active", "undeploy"): ["undeploy", None, "cleaning_after_delete"],
}

_FAILED_STATES = ("deploy failed", "clean failed")
_KIND_BY_STATE = {
    "verifying": "verifying",
    "manageable": "manageable",
    "cleaning": "cleaning",
    "available": "available",
    "inspecting": "inspecting",
    "deploying": "deploying",
    "active": "active",
    "deleting": "deleting",
}
_RAID_OK = ("agent", "hardware")
_GIB = 1024**3


def _build_steps(
    states: list[str], delays: list[Optional[str]], cfg: SimConfig, now: float
) -> list[Step]:
    steps: list[Step] = []
    due = float(now)
    for state, delay in zip(states, delays):
        if delay is not None:
            due += cfg.duration(delay)
        steps.append(Step(state, due, _KIND_BY_STATE[state]))  # type: ignore[arg-type]
    return steps


def plan(node: Any, verb: str, cfg: SimConfig, now: float) -> list[Step]:
    """Return the ordered steps for ``verb`` on ``node`` at virtual time ``now``.

    Raises NodeNotProvided (provide on ``available``) or InvalidState.
    """
    state = node.provision_state
    key = (state, verb)
    if verb == "provide" and state == "available":
        raise NodeNotProvided(messages.node_not_provided(node.id))
    if key not in STATE_MACHINE_TABLE:
        raise InvalidState(messages.invalid_state(state, node.id))
    maintenance = bool(getattr(node, "maintenance", False))
    if maintenance and (
        verb == "provide" or (verb == "clean" and state not in _FAILED_STATES)
    ):
        raise InvalidState(messages.invalid_state(state, node.id))

    states = list(STATE_MACHINE_TABLE[key])
    delays = list(_STEP_DELAYS[key])
    steps = _build_steps(states, delays, cfg, now)
    if not cfg.features.deleting_state:
        steps = [s for s in steps if s.kind != "deleting"]
    return steps


def plan_deploy(cfg: SimConfig, now: float) -> list[Step]:
    """Steps ``deploying`` then ``active`` for a new server (T4)."""
    return _build_steps(
        ["deploying", "active"], [None, "deploy"], cfg, now
    )


def pending_for(
    node: Any, verb: str, cfg: SimConfig, now: float, server_id: str | None = None
) -> PendingTransition:
    steps = plan(node, verb, cfg, now)
    return PendingTransition(
        node_id=node.id,
        steps=steps,
        verb=verb,
        final_state=steps[-1].to_state,
        server_id=server_id,
    )


class FailureInjector:
    """One-shot failure injection per (node, op)."""

    DEFAULT_MESSAGE = "injected failure"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, str], str] = {}

    def set(self, node_id: str, op: str, message: str | None = None) -> None:
        with self._lock:
            self._pending[(node_id, op)] = message or self.DEFAULT_MESSAGE

    def take(self, node_id: str, op: str) -> str | None:
        """Return and clear the injected message, or None."""
        with self._lock:
            return self._pending.pop((node_id, op), None)

    def peek(self, node_id: str, op: str) -> str | None:
        with self._lock:
            return self._pending.get((node_id, op))


def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def deploy_preflight(
    node: Any,
    ports: Iterable[Any],
    flavor: Any,
    image: Any,
    cfg: SimConfig,
    injected: str | None = None,
) -> str | None:
    """Return the ``last_error`` text of the first failing check, else None."""
    if injected:
        return injected
    if node.power_state is None:
        return "power state is None"
    ports = list(ports)
    if cfg.guards.enforce_pxe_port and not any(
        getattr(p, "pxe_enabled", True) for p in ports
    ):
        return "no PXE-enabled port"
    if node.network_interface == "noop":
        return "network interface noop cannot deploy instances"
    if any(not getattr(p, "vif_bind_ok", True) for p in ports):
        return "VIF binding failed for node port"
    if node.target_raid_config and node.raid_interface not in _RAID_OK:
        return f"RAID interface {node.raid_interface} does not support target_raid_config"

    props = node.properties or {}
    local_gb = node_capacity(node, "local_gb")
    root_gb = props.get("root_gb")
    if isinstance(root_gb, (int, float)) and not isinstance(root_gb, bool):
        min_disk = _attr(image, "min_disk") if image is not None else None
        if root_gb > local_gb:
            return f"root_gb {root_gb} is larger than local_gb {local_gb}"
        if isinstance(min_disk, (int, float)) and root_gb < min_disk:
            return f"root_gb {root_gb} is smaller than image minimum disk {min_disk}"
    if image is not None:
        size = _attr(image, "size")
        whole = not _attr(image, "kernel_id") and not _attr(image, "ramdisk_id")
        img_type = _attr(image, "img_type")
        if img_type and str(img_type).lower() in ("ami", "raw"):
            whole = True
        if (
            whole
            and isinstance(size, (int, float))
            and not isinstance(size, bool)
            and size > local_gb * _GIB
        ):
            return f"image size {size} is larger than local_gb {local_gb}"
    if not cfg.strict_mode and flavor is not None and flavor.disk > local_gb:
        return f"flavor disk {flavor.disk} is larger than local_gb {local_gb}"
    return None


@dataclass
class ApplyContext:
    """Collaborators needed when applying steps."""

    cfg: SimConfig
    ports: Callable[[str], Iterable[Any]] = lambda node_id: ()
    servers: MutableMapping[str, Any] = field(default_factory=dict)
    flavors: Mapping[str, Any] = field(default_factory=dict)
    images: Any = None  # ImageLookup
    placement: Any = None  # PlacementService
    pending: Optional[MutableMapping[str, PendingTransition]] = None

    def flavor_for(self, server: Any) -> Any:
        if server is None:
            return None
        ref = server.flavor
        if ref in self.flavors:
            return self.flavors[ref]
        for f in self.flavors.values():
            if getattr(f, "name", None) == ref:
                return f
        return None

    def image_for(self, server: Any) -> Any:
        if server is None or self.images is None:
            return None
        return self.images.get(server.image)


def _fail_deploy(
    node: Any, pending: PendingTransition, error: str, ctx: ApplyContext
) -> None:
    node.provision_state = "deploy failed"
    node.target_provision_state = None
    node.last_error = error
    server = ctx.servers.get(pending.server_id) if pending.server_id else None
    if server is not None:
        server.status = "ERROR"
        server.task_state = None
        server.fault = {
            "message": messages.deploy_failed(error),
            "code": 500,
            "created": _now_timestamp(),
        }
    if ctx.placement is not None and pending.server_id:
        ctx.placement.release(pending.server_id)


def _fail_clean(node: Any, error: str) -> None:
    node.provision_state = "clean failed"
    node.target_provision_state = None
    node.last_error = error


def apply_due(
    node: Any,
    pending: PendingTransition,
    now: float,
    failures: FailureInjector,
    ctx: ApplyContext,
) -> bool:
    """Apply every step of ``pending`` with ``due_at <= now``, in order.

    Returns True when the transition is finished (all steps applied or a
    failure ended it); the record is then removed from ``ctx.pending``.
    """
    finished = False
    while pending.steps and pending.steps[0].due_at <= now:
        step = pending.steps.pop(0)
        node.provision_state = step.to_state
        node.provision_updated_at = step.due_at
        server = ctx.servers.get(pending.server_id) if pending.server_id else None

        if step.kind == "cleaning":
            injected = failures.take(node.id, "clean")
            if injected:
                _fail_clean(node, injected)
                finished = True
                break
        elif step.kind == "deploying":
            injected = failures.take(node.id, "deploy")
            error = deploy_preflight(
                node,
                ctx.ports(node.id),
                ctx.flavor_for(server),
                ctx.image_for(server),
                ctx.cfg,
                injected,
            )
            if error:
                _fail_deploy(node, pending, error, ctx)
                finished = True
                break
        elif step.kind == "active":
            if server is not None:
                server.status = "ACTIVE"
                server.task_state = None
        elif step.kind == "available":
            node.last_error = None
            node.instance_uuid = None

        if not pending.steps:
            node.target_provision_state = None
            finished = True

    if finished:
        pending.steps.clear()
        if ctx.pending is not None:
            ctx.pending.pop(node.id, None)
    return finished
