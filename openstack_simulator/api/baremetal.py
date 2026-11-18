"""Ironic Baremetal API v1 endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request, jsonify

from openstack_simulator import messages
from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    BadRequest,
    DuplicateResourceError,
    NodeLocked,
    NotAuthorized,
    InvalidState,
    InvalidPatchError,
    InvalidStateError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)

baremetal_bp = Blueprint("baremetal", __name__, url_prefix="/baremetal/v1")

PROVISION_TARGETS = (
    "manage", "provide", "clean", "inspect", "deploy", "undeploy", "active", "deleted",
)
_DEPLOY_TARGETS = ("deploy", "active")
_FIELD_PATHS = (
    "/owner", "/lessee", "/maintenance", "/maintenance_reason",
    "/resource_class", "/protected", "/target_raid_config",
)

VALIDATE_INTERFACES = (
    "bios",
    "boot",
    "console",
    "deploy",
    "inspect",
    "management",
    "network",
    "power",
    "raid",
    "rescue",
    "storage",
)


# --- Node endpoints ---


@baremetal_bp.route("/nodes", methods=["GET"])
@require_token
def list_nodes():
    """List all active baremetal nodes."""
    sim = get_simulator()
    nodes = sim.node_service.visible_nodes(g.caller_context)
    return jsonify({"nodes": [n.to_dict() for n in nodes]})


@baremetal_bp.route("/nodes", methods=["POST"])
@require_token
def create_node():
    """Create a new baremetal node."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}

    name = data.get("name", "")
    driver = data.get("driver", "")

    if not name:
        return jsonify({"error": {"message": "Node name is required", "code": 400}}), 400
    if not driver:
        return jsonify({"error": {"message": "Node driver is required", "code": 400}}), 400

    try:
        node = sim.baremetal_manager.create_node(
            name=name,
            driver=driver,
            memory_mb=data.get("memory_mb", 0),
            cpus=data.get("cpus", 0),
            local_gb=data.get("local_gb", 0),
            cpu_arch=data.get("cpu_arch", "x86_64"),
            driver_info=data.get("driver_info"),
            properties=data.get("properties"),
        )
    except ResourceLimitExceededError as e:
        return jsonify({"overLimit": {"message": str(e), "code": 413}}), 413
    except DuplicateResourceError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409

    return jsonify(node.to_dict()), 201


@baremetal_bp.route("/nodes/detail", methods=["GET"])
@require_token
def list_nodes_detail():
    """List all active baremetal nodes with full detail."""
    sim = get_simulator()
    nodes = sim.node_service.visible_nodes(g.caller_context)
    return jsonify({"nodes": [n.to_dict() for n in nodes]})


@baremetal_bp.route("/nodes/<node_ident>/validate", methods=["GET"])
@require_token
def validate_node(node_ident: str):
    """Validate a baremetal node's interfaces (always succeeds)."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    return jsonify({
        iface: {"result": True, "reason": None} for iface in VALIDATE_INTERFACES
    })


@baremetal_bp.route("/nodes/<node_ident>/ports", methods=["GET"])
@require_token
def list_node_ports(node_ident: str):
    """List ports belonging to a baremetal node."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    ports = sim.baremetal_manager.list_ports(node_id=node.id)
    return jsonify({"ports": [p.to_dict() for p in ports]})


@baremetal_bp.route("/nodes/<node_ident>", methods=["GET"])
@require_token
def get_node(node_ident: str):
    """Get a baremetal node by name or UUID."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    return jsonify(node.to_dict())


@baremetal_bp.route("/nodes/<node_ident>", methods=["PATCH"])
@require_token
def update_node(node_ident: str):
    """Update a baremetal node's properties."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    data = request.get_json(silent=True)
    if data is None:
        data = {}

    try:
        if isinstance(data, list):
            data = _apply_node_field_ops(sim, node, data)
            updated_node = sim.baremetal_manager.patch_node(node.name, data)
        elif isinstance(data, dict):
            updated_node = sim.baremetal_manager.update_node(node.name, **data)
        else:
            raise InvalidPatchError("Patch body must be a list of operations")
    except InvalidPatchError as e:
        return jsonify({"error": {"message": str(e), "code": 400}}), 400
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404
    except DuplicateResourceError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409

    return jsonify(updated_node.to_dict()), 200


@baremetal_bp.route("/nodes/<node_ident>", methods=["DELETE"])
@require_token
def delete_node(node_ident: str):
    """Soft-delete a baremetal node."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    try:
        sim.baremetal_manager.delete_node(node.name)
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404

    return "", 204


@baremetal_bp.route("/nodes/<node_ident>/states/power", methods=["PUT"])
@require_token
def set_power_state(node_ident: str):
    """Change the power state of a baremetal node."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target", "")

    if not target:
        return jsonify({"error": {"message": "Power state target is required", "code": 400}}), 400

    try:
        sim.baremetal_manager.set_power_state(node.name, target)
    except InvalidStateError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404

    return "", 202


@baremetal_bp.route("/nodes/<node_ident>/states/provision", methods=["PUT"])
@require_token
def set_provision_state(node_ident: str):
    """Change the provision state of a baremetal node."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404

    data = request.get_json(silent=True) or {}
    target = data.get("target", "")

    if not target:
        return jsonify({"error": {"message": "Provision state target is required", "code": 400}}), 400

    if target not in PROVISION_TARGETS:
        return jsonify({"error": {"message": f"Invalid provision target: {target}", "code": 400}}), 400

    ctx = g.caller_context
    svc = sim.node_service
    try:
        if target in _DEPLOY_TARGETS:
            _deploy(sim, ctx, node, target)
        elif target == "deleted":
            _require_admin(ctx)
            sim.baremetal_manager.set_provision_state(node.name, "deleted")
        elif target == "clean" and node.provision_state == "manageable":
            # Legacy: clean on a manageable node returns to manageable.
            _require_admin(ctx)
            sim.baremetal_manager.set_provision_state(node.name, "clean")
        else:
            svc.provision(ctx, node.id, target)
    except InvalidStateError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404

    return "", 202


def _require_admin(ctx) -> None:
    if not ctx.is_admin:
        raise NotAuthorized(messages.admin_required())


def _deploy(sim, ctx, node, target: str) -> None:
    """Deploy (``active``/``deploy``): lessee check, lock check, then deploy."""
    svc = sim.node_service
    with svc.lock:
        svc.sync(ctx.now)
        if node.lessee and node.lessee != ctx.project_id:
            raise NotAuthorized(messages.not_authorized(node.id))
        _require_admin(ctx)
        if node.target_provision_state is not None:
            raise NodeLocked(messages.node_locked(node.id))
        sim.baremetal_manager.set_provision_state(node.name, "active")


@baremetal_bp.route("/nodes/<node_ident>/maintenance", methods=["PUT"])
@require_token
def set_node_maintenance(node_ident: str):
    """Set the maintenance flag (optional ``reason``)."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404
    data = request.get_json(silent=True)
    reason = data.get("reason") if isinstance(data, dict) else None
    sim.node_service.set_maintenance(node.id, True, reason)
    return "", 202


@baremetal_bp.route("/nodes/<node_ident>/maintenance", methods=["DELETE"])
@require_token
def clear_node_maintenance(node_ident: str):
    """Clear the maintenance flag."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404
    sim.node_service.set_maintenance(node.id, False, None)
    return "", 202


@baremetal_bp.route("/nodes/<node_ident>/traits/<trait>", methods=["PUT"])
@require_token
def add_node_trait(node_ident: str, trait: str):
    """Add a trait to a node (normalized, copied to Placement)."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404
    sim.node_service.add_trait(node.id, trait)
    return "", 204


@baremetal_bp.route("/nodes/<node_ident>/traits/<trait>", methods=["DELETE"])
@require_token
def remove_node_trait(node_ident: str, trait: str):
    """Remove one trait from a node."""
    sim = get_simulator()
    node = _find_node(sim, node_ident)
    if node is None:
        return jsonify({"error": {"message": f"Node {node_ident} not found", "code": 404}}), 404
    sim.node_service.remove_trait(node.id, trait)
    return "", 204


def _validate_raid_config(value) -> None:
    """Root logical disk of a target_raid_config must be RAID 1."""
    if value is None:
        return
    disks = value.get("logical_disks") if isinstance(value, dict) else None
    if not isinstance(disks, list):
        raise BadRequest("target_raid_config requires a 'logical_disks' list")
    for disk in disks:
        if not isinstance(disk, dict):
            raise BadRequest("Each logical disk must be an object")
        if disk.get("is_root_volume") and str(disk.get("raid_level")) != "1":
            raise BadRequest("The root logical disk must be RAID 1")


def _apply_node_field_ops(sim, node, ops: list) -> list:
    """Apply PATCH ops on the new node fields; return the remaining ops."""
    ctx = g.caller_context
    svc = sim.node_service
    mine, rest = [], []
    for op in ops:
        path = op.get("path") if isinstance(op, dict) else None
        (mine if path in _FIELD_PATHS else rest).append(op)

    # Validate everything before mutating anything.
    parsed = []
    for op in mine:
        kind = op.get("op")
        path = op["path"]
        if kind not in ("add", "replace", "remove"):
            raise InvalidPatchError(f"Unsupported patch op '{kind}'")
        if kind != "remove" and "value" not in op:
            raise InvalidPatchError(f"Patch op '{kind}' on '{path}' requires 'value'")
        value = None if kind == "remove" else op["value"]
        if path in ("/maintenance", "/protected"):
            if kind == "remove":
                value = False
            elif not isinstance(value, bool):
                raise InvalidPatchError(f"'{path}' value must be a boolean")
        elif path in ("/owner", "/lessee", "/maintenance_reason", "/resource_class"):
            if value is not None and not isinstance(value, str):
                raise InvalidPatchError(f"'{path}' value must be a string")
        elif path == "/target_raid_config":
            _validate_raid_config(value)
        parsed.append((path, value))

    for path, value in parsed:
        if path == "/owner":
            svc.set_owner(ctx, node.id, value)
        elif path == "/lessee":
            svc.set_lessee(ctx, node.id, value)
        elif path == "/maintenance":
            svc.set_maintenance(node.id, value, node.maintenance_reason if value else None)
        elif path == "/maintenance_reason":
            svc.set_maintenance(node.id, bool(node.maintenance), value)
        elif path == "/resource_class":
            svc.set_resource_class(node.id, value)
        elif path == "/protected":
            svc.set_protected(node.id, value)
        elif path == "/target_raid_config":
            svc.set_target_raid_config(node.id, value)
    return rest


# --- Port endpoints ---


@baremetal_bp.route("/ports", methods=["GET"])
@require_token
def list_ports():
    """List all active baremetal ports, optionally filtered by node_id."""
    sim = get_simulator()
    node_id = request.args.get("node_id")
    ports = sim.baremetal_manager.list_ports(node_id=node_id)
    return jsonify({"ports": [p.to_dict() for p in ports]})


@baremetal_bp.route("/ports/detail", methods=["GET"])
@require_token
def list_ports_detail():
    """List all active baremetal ports with detail, optionally filtered by node_id."""
    sim = get_simulator()
    node_id = request.args.get("node_id")
    ports = sim.baremetal_manager.list_ports(node_id=node_id)
    return jsonify({"ports": [p.to_dict() for p in ports]})


@baremetal_bp.route("/ports", methods=["POST"])
@require_token
def create_port():
    """Create a new baremetal port."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}

    node_id = data.get("node_id", "")
    address = data.get("address", "")

    if not node_id:
        return jsonify({"error": {"message": "Port node_id is required", "code": 400}}), 400
    if not address:
        return jsonify({"error": {"message": "Port address (MAC) is required", "code": 400}}), 400

    try:
        port = sim.baremetal_manager.create_port(node_id=node_id, address=address)
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404
    except DuplicateResourceError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409
    except ResourceLimitExceededError as e:
        return jsonify({"overLimit": {"message": str(e), "code": 413}}), 413

    return jsonify(port.to_dict()), 201


@baremetal_bp.route("/ports/<port_ident>", methods=["DELETE"])
@require_token
def delete_port(port_ident: str):
    """Soft-delete a baremetal port."""
    sim = get_simulator()
    port = _find_port(sim, port_ident)
    if port is None:
        return jsonify({"error": {"message": f"Port {port_ident} not found", "code": 404}}), 404

    try:
        sim.baremetal_manager.delete_port(port.address)
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404

    return "", 204


# --- Helpers ---


def _find_node(sim, identifier: str):
    """Find a baremetal node by name or UUID."""
    # Try by name first
    node = sim.baremetal_manager.get_node(identifier)
    if node:
        return node

    # Try by UUID
    for n in sim.baremetal_manager.list_nodes():
        if n.id == identifier:
            return n

    return None


def _find_port(sim, identifier: str):
    """Find a baremetal port by MAC address or UUID."""
    # Try by MAC address (the store key)
    ports = sim.baremetal_manager.list_ports()
    for p in ports:
        if p.address == identifier or p.id == identifier:
            return p

    return None
