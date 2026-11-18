"""Simulator control endpoints (``/_sim``): settle, clock, failure injection, consistency.

All endpoints require an admin token.
"""

from __future__ import annotations

import math
from functools import wraps

from flask import Blueprint, g, jsonify, request

from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    BadRequest,
    Forbidden,
    ResourceNotFoundError,
    SimError,
)

sim_control_bp = Blueprint("sim_control", __name__, url_prefix="/_sim")

MAX_SETTLE_STEPS = 1000
_FAIL_OPS = ("deploy", "clean")


def _admin_only(f):
    """Require a valid token whose caller is an admin."""

    @require_token
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.caller_context.is_admin:
            raise Forbidden("Admin privileges are required.")
        return f(*args, **kwargs)

    return decorated


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    return body


@sim_control_bp.route("/settle", methods=["POST"])
@_admin_only
def settle():
    """Advance the clock until no transition is pending (bounded)."""
    sim = get_simulator()
    with sim.lock:
        affected: dict[str, None] = {}
        for node_id in sim.store.pending:
            affected[node_id] = None

        bound_reached = False
        steps = 0
        while True:
            due_times = [
                p.steps[0].due_at for p in sim.store.pending.values() if p.steps
            ]
            if not due_times:
                # Drop empty records, if any.
                for node_id in [n for n, p in sim.store.pending.items() if not p.steps]:
                    del sim.store.pending[node_id]
                break
            if steps >= MAX_SETTLE_STEPS:
                bound_reached = True
                break
            steps += 1
            target = min(due_times)
            current = sim.clock.now()
            if target > current:
                sim.clock.advance(target - current)
            sim.node_service.sync(max(target, sim.clock.now()))

        nodes = []
        for node_id in affected:
            node = sim.store.get("baremetal_nodes", node_id)
            if node is not None:
                nodes.append(
                    {"uuid": node.id, "provision_state": node.provision_state}
                )
    return jsonify({"nodes": nodes, "bound_reached": bound_reached}), 200


@sim_control_bp.route("/clock/advance", methods=["POST"])
@_admin_only
def advance_clock():
    """Advance the persistent virtual clock by ``seconds``."""
    sim = get_simulator()
    seconds = _json_body().get("seconds")
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise BadRequest("'seconds' must be a finite number >= 0.")
    with sim.lock:
        now = sim.clock.advance(seconds)
    return jsonify({"now": now}), 200


@sim_control_bp.route("/nodes/<uuid>/fail-next", methods=["POST"])
@_admin_only
def fail_next(uuid):
    """Inject a one-shot failure for the next deploy or clean of a node."""
    sim = get_simulator()
    body = _json_body()
    op = body.get("op")
    if op not in _FAIL_OPS:
        raise BadRequest("'op' must be 'deploy' or 'clean'.")
    message = body.get("last_error")
    if message is None:
        message = sim.failures.DEFAULT_MESSAGE
    elif not isinstance(message, str):
        raise BadRequest("'last_error' must be a string.")
    with sim.lock:
        try:
            node = sim.node_service._find(uuid)
        except ResourceNotFoundError:
            raise SimError(
                404, "itemNotFound", f"Baremetal node '{uuid}' not found"
            ) from None
        sim.failures.set(node.id, op, message or None)
    return jsonify({"node": node.id, "op": op, "last_error": message or sim.failures.DEFAULT_MESSAGE}), 200


@sim_control_bp.route("/consistency", methods=["GET"])
@_admin_only
def consistency():
    """Report allocation, instance and trait inconsistencies."""
    sim = get_simulator()
    with sim.lock:
        nodes = sim.node_service.sync(g.caller_context.now)
        providers = sim.placement.snapshot()
        report = {
            "available_with_allocation": [],
            "active_without_allocation": [],
            "instance_mismatch": [],
            "trait_mismatch": [],
        }
        for node in nodes:
            provider = providers.get(node.id)
            allocations = dict(provider.allocations) if provider else {}
            if node.provision_state == "available" and allocations:
                report["available_with_allocation"].append(node.id)
            if node.provision_state == "active" and not allocations:
                report["active_without_allocation"].append(node.id)
            if (
                allocations
                and node.instance_uuid is not None
                and node.instance_uuid not in allocations
            ):
                report["instance_mismatch"].append(
                    {
                        "node": node.id,
                        "instance_uuid": node.instance_uuid,
                        "allocation_consumers": sorted(allocations),
                    }
                )
            if provider is not None:
                node_traits = set(node.traits or [])
                provider_traits = set(provider.traits)
                if node_traits != provider_traits:
                    report["trait_mismatch"].append(
                        {
                            "node": node.id,
                            "node_traits": sorted(node_traits),
                            "provider_traits": sorted(provider_traits),
                            "difference": sorted(node_traits ^ provider_traits),
                        }
                    )
    return jsonify(report), 200
