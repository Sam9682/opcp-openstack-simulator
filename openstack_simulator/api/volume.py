"""Cinder Volume API v3 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    DuplicateResourceError,
    InvalidStateError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)

volume_bp = Blueprint("volume", __name__, url_prefix="/volume/v3")


@volume_bp.route("/<project_id>/volumes", methods=["GET"])
@volume_bp.route("/<project_id>/volumes/detail", methods=["GET"])
@require_token
def list_volumes(project_id: str):
    """List all volumes."""
    sim = get_simulator()
    volumes = sim.volume_manager.list()
    return jsonify({"volumes": [_volume_to_dict(v) for v in volumes]})


@volume_bp.route("/<project_id>/volumes", methods=["POST"])
@require_token
def create_volume(project_id: str):
    """Create a volume."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    vol_data = data.get("volume", {})

    name = vol_data.get("name", "")
    size = vol_data.get("size", 1)

    if not name:
        return jsonify({"badRequest": {"message": "Volume name is required", "code": 400}}), 400

    try:
        volume = sim.volume_manager.create(name, int(size))
    except ResourceLimitExceededError as e:
        return jsonify({"overLimit": {"message": str(e), "code": 413}}), 413
    except DuplicateResourceError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409

    return jsonify({"volume": _volume_to_dict(volume)}), 202


@volume_bp.route("/<project_id>/volumes/<volume_id>", methods=["GET"])
@require_token
def get_volume(project_id: str, volume_id: str):
    """Get a volume by ID or name."""
    sim = get_simulator()
    volume = _find_volume(sim, volume_id)
    if volume is None:
        return jsonify({"itemNotFound": {"message": f"Volume {volume_id} not found", "code": 404}}), 404

    return jsonify({"volume": _volume_to_dict(volume)})


@volume_bp.route("/<project_id>/volumes/<volume_id>", methods=["DELETE"])
@require_token
def delete_volume(project_id: str, volume_id: str):
    """Delete a volume."""
    sim = get_simulator()
    volume = _find_volume(sim, volume_id)
    if volume is None:
        return jsonify({"itemNotFound": {"message": f"Volume {volume_id} not found", "code": 404}}), 404

    try:
        sim.volume_manager.delete(volume.name)
    except ResourceNotFoundError as e:
        return jsonify({"itemNotFound": {"message": str(e), "code": 404}}), 404
    except InvalidStateError as e:
        return jsonify({"conflict": {"message": str(e), "code": 409}}), 409

    return "", 204


@volume_bp.route("/<project_id>/volumes/<volume_id>/action", methods=["POST"])
@require_token
def volume_action(project_id: str, volume_id: str):
    """Perform an action on a volume (attach, detach, snapshot)."""
    sim = get_simulator()
    volume = _find_volume(sim, volume_id)
    if volume is None:
        return jsonify({"itemNotFound": {"message": f"Volume {volume_id} not found", "code": 404}}), 404

    data = request.get_json(silent=True) or {}

    if "os-attach" in data:
        instance_id = data["os-attach"].get("instance_uuid", "")
        # Find instance by ID to get its name
        instance = _find_instance_by_id(sim, instance_id)
        if instance is None:
            return jsonify({"itemNotFound": {"message": f"Instance {instance_id} not found", "code": 404}}), 404
        try:
            sim.volume_manager.attach(volume.name, instance.name)
        except InvalidStateError as e:
            return jsonify({"conflict": {"message": str(e), "code": 409}}), 409
        except ResourceNotFoundError as e:
            return jsonify({"itemNotFound": {"message": str(e), "code": 404}}), 404
        return "", 202

    if "os-create_snapshot" in data or "createSnapshot" in data:
        snap_data = data.get("os-create_snapshot", data.get("createSnapshot", {}))
        snap_name = snap_data.get("name", "snapshot")
        try:
            snap = sim.volume_manager.snapshot(volume.name, snap_name)
        except ResourceNotFoundError as e:
            return jsonify({"itemNotFound": {"message": str(e), "code": 404}}), 404
        return jsonify({"snapshot": {"id": snap.id, "name": snap.name, "volume_id": snap.source_id, "status": "available", "created_at": snap.created_at}}), 202

    return jsonify({"badRequest": {"message": "Unknown action", "code": 400}}), 400


# --- Helpers ---

def _volume_to_dict(volume) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    attachments = []
    if volume.attached_to:
        attachments.append({
            "server_id": volume.attached_to,
            "attachment_id": f"attach-{volume.id[:8]}",
            "volume_id": volume.id,
            "device": "/dev/vdb",
        })

    return {
        "id": volume.id,
        "name": volume.name,
        "size": volume.size,
        "status": volume.status,
        "created_at": volume.created_at,
        "volume_type": "standard",
        "attachments": attachments,
        "availability_zone": "nova",
        "os-vol-tenant-attr:tenant_id": project_id,
        "metadata": {},
    }


def _find_volume(sim, identifier: str):
    """Find a volume by ID or name."""
    volume = sim.volume_manager.get(identifier)
    if volume:
        return volume
    for v in sim.volume_manager.list():
        if v.id == identifier:
            return v
    return None


def _find_instance_by_id(sim, instance_id: str):
    """Find an instance by its UUID."""
    for inst in sim.compute_manager.list():
        if inst.id == instance_id:
            return inst
    return None
