"""Nova Compute API v2.1 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)
from openstack_simulator.models import _generate_id

compute_bp = Blueprint("compute", __name__, url_prefix="/compute/v2.1")


def _instance_to_server(instance, project_id: str) -> dict:
    """Convert an Instance model to a Nova server response dict."""
    return {
        "id": instance.id,
        "name": instance.name,
        "status": instance.status,
        "tenant_id": project_id,
        "user_id": "fake-user-id",
        "flavor": {"id": instance.flavor, "links": []},
        "image": {"id": instance.image, "links": []},
        "created": instance.created_at,
        "updated": instance.created_at,
        "addresses": {},
        "links": [],
        "OS-EXT-STS:task_state": None,
        "OS-EXT-STS:vm_state": instance.status.lower() if instance.status != "DELETED" else "deleted",
        "OS-EXT-STS:power_state": 1 if instance.status == "ACTIVE" else 0,
        "os-extended-volumes:volumes_attached": [],
        "metadata": {},
    }


@compute_bp.route("/servers", methods=["GET"])
@require_token
def list_servers():
    """List all servers (instances)."""
    sim = get_simulator()
    project_id = current_app.config["PROJECT_ID"]
    instances = sim.compute_manager.list()

    detail = "/detail" in request.path
    servers = [_instance_to_server(i, project_id) for i in instances]
    return jsonify({"servers": servers})


@compute_bp.route("/servers/detail", methods=["GET"])
@require_token
def list_servers_detail():
    """List all servers with full details."""
    sim = get_simulator()
    project_id = current_app.config["PROJECT_ID"]
    instances = sim.compute_manager.list()
    servers = [_instance_to_server(i, project_id) for i in instances]
    return jsonify({"servers": servers})


@compute_bp.route("/servers", methods=["POST"])
@require_token
def create_server():
    """Create a new server (instance)."""
    sim = get_simulator()
    project_id = current_app.config["PROJECT_ID"]
    data = request.get_json(silent=True) or {}
    server_data = data.get("server", {})

    name = server_data.get("name", "")
    flavor_ref = server_data.get("flavorRef", sim.config.get("default_flavor", "m1.small"))
    image_ref = server_data.get("imageRef", sim.config.get("default_image", "ubuntu-22.04"))

    if not name:
        return jsonify({"badRequest": {"message": "Server name is required", "code": 400}}), 400

    try:
        instance = sim.compute_manager.create(name, flavor_ref, image_ref)
    except ResourceLimitExceededError as e:
        return jsonify({"overLimit": {"message": str(e), "code": 413}}), 413
    except DuplicateResourceError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409

    server = _instance_to_server(instance, project_id)
    server["adminPass"] = "simulated-password"
    return jsonify({"server": server}), 202


@compute_bp.route("/servers/<server_id>", methods=["GET"])
@require_token
def get_server(server_id: str):
    """Get a server by ID or name."""
    sim = get_simulator()
    project_id = current_app.config["PROJECT_ID"]

    # Try by ID first, then by name
    instance = _find_instance(sim, server_id)
    if instance is None:
        return jsonify({"itemNotFound": {"message": f"Instance {server_id} not found", "code": 404}}), 404

    return jsonify({"server": _instance_to_server(instance, project_id)})


@compute_bp.route("/servers/<server_id>", methods=["DELETE"])
@require_token
def delete_server(server_id: str):
    """Delete a server."""
    sim = get_simulator()
    instance = _find_instance(sim, server_id)
    if instance is None:
        return jsonify({"itemNotFound": {"message": f"Instance {server_id} not found", "code": 404}}), 404

    try:
        sim.compute_manager.delete(instance.name)
    except ResourceNotFoundError as e:
        return jsonify({"itemNotFound": {"message": str(e), "code": 404}}), 404

    return "", 204


@compute_bp.route("/servers/<server_id>/action", methods=["POST"])
@require_token
def server_action(server_id: str):
    """Perform an action on a server (resize, createImage, etc.)."""
    sim = get_simulator()
    instance = _find_instance(sim, server_id)
    if instance is None:
        return jsonify({"itemNotFound": {"message": f"Instance {server_id} not found", "code": 404}}), 404

    data = request.get_json(silent=True) or {}

    if "resize" in data:
        flavor = data["resize"].get("flavorRef", "m1.small")
        sim.compute_manager.resize(instance.name, flavor)
        return "", 202

    if "createImage" in data:
        image_name = data["createImage"].get("name", "snapshot")
        snap = sim.compute_manager.snapshot(instance.name, image_name)
        return jsonify({"imageId": snap.id}), 202

    return jsonify({"badRequest": {"message": "Unknown action", "code": 400}}), 400


@compute_bp.route("/flavors", methods=["GET"])
@compute_bp.route("/flavors/detail", methods=["GET"])
@require_token
def list_flavors():
    """List available flavors (static)."""
    flavors = [
        {"id": "m1.tiny", "name": "m1.tiny", "ram": 512, "vcpus": 1, "disk": 1},
        {"id": "m1.small", "name": "m1.small", "ram": 2048, "vcpus": 1, "disk": 20},
        {"id": "m1.medium", "name": "m1.medium", "ram": 4096, "vcpus": 2, "disk": 40},
        {"id": "m1.large", "name": "m1.large", "ram": 8192, "vcpus": 4, "disk": 80},
        {"id": "m1.xlarge", "name": "m1.xlarge", "ram": 16384, "vcpus": 8, "disk": 160},
    ]
    return jsonify({"flavors": flavors})


@compute_bp.route("/images", methods=["GET"])
@compute_bp.route("/images/detail", methods=["GET"])
@require_token
def list_images():
    """List available images (static)."""
    images = [
        {"id": "ubuntu-22.04", "name": "ubuntu-22.04", "status": "ACTIVE", "metadata": {}},
        {"id": "ubuntu-20.04", "name": "ubuntu-20.04", "status": "ACTIVE", "metadata": {}},
        {"id": "centos-8", "name": "centos-8", "status": "ACTIVE", "metadata": {}},
        {"id": "debian-11", "name": "debian-11", "status": "ACTIVE", "metadata": {}},
    ]
    return jsonify({"images": images})


def _find_instance(sim, identifier: str):
    """Find an instance by ID or name."""
    # Try by name first (most common in training)
    instance = sim.compute_manager.get(identifier)
    if instance:
        return instance

    # Try by ID
    for inst in sim.compute_manager.list():
        if inst.id == identifier:
            return inst

    return None
