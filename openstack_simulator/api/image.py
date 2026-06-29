"""Glance Image API v2 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import (
    get_simulator,
    get_base_url,
    require_token,
)

image_bp = Blueprint("image", __name__, url_prefix="/image")


@image_bp.route("/", methods=["GET"])
@image_bp.route("/v2/", methods=["GET"])
def version_discovery():
    """Glance version discovery."""
    base_url = get_base_url()
    return jsonify({
        "version": {
            "id": "v2.0",
            "status": "stable",
            "updated": "2020-04-07T00:00:00Z",
            "links": [{"rel": "self", "href": f"{base_url}/image/v2/"}],
            "media-types": [
                {"base": "application/json", "type": "application/vnd.openstack.image-v2+json"}
            ],
        }
    })


@image_bp.route("/v2/images", methods=["GET"])
@require_token
def list_images():
    """List images."""
    # Return empty list for now since we don't implement image management yet
    return jsonify({
        "images": [],
        "schema": "image"
    })


@image_bp.route("/v2/images/<image_id>", methods=["GET"])
@require_token
def get_image(image_id):
    """Get image details."""
    # Return empty response for now since we don't implement image management yet
    return jsonify({
        "id": image_id,
        "name": "dummy-image",
        "status": "active",
        "visibility": "private",
        "size": 0,
        "disk_format": "qcow2",
        "container_format": "bare",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": "2023-01-01T00:00:00Z",
        "schema": "image"
    })
