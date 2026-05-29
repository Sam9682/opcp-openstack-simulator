"""Ironic Baremetal API v1 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify

from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidStateError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)

baremetal_bp = Blueprint("baremetal", __name__, url_prefix="/baremetal/v1")


# --- Node endpoints ---


@baremetal_bp.route("/nodes", methods=["GET"])
@require_token
def list_nodes():
    """List all active baremetal nodes."""
    sim = get_simulator()
    nodes = sim.baremetal_manager.list_nodes()
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

    data = request.get_json(silent=True) or {}

    try:
        updated_node = sim.baremetal_manager.update_node(node.name, **data)
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

    try:
        sim.baremetal_manager.set_provision_state(node.name, target)
    except InvalidStateError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409
    except ResourceNotFoundError as e:
        return jsonify({"error": {"message": str(e), "code": 404}}), 404

    return "", 202


# --- Port endpoints ---


@baremetal_bp.route("/ports", methods=["GET"])
@require_token
def list_ports():
    """List all active baremetal ports, optionally filtered by node_id."""
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
