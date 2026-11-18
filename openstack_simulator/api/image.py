"""Glance Image API v2 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, make_response

from openstack_simulator.api.helpers import (
    get_simulator,
    get_base_url,
    require_token,
)
from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceNotFoundError,
)

image_bp = Blueprint("image", __name__, url_prefix="/image")

_REASONS = {
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
}
_STR_ATTRS = ("disk_format", "container_format", "visibility")
_INT_ATTRS = ("min_disk", "min_ram")


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


def _error(status: int, message: str):
    """Build a JSON error response."""
    resp = jsonify({"code": status, "title": _REASONS[status], "message": message})
    resp.status_code = status
    return resp


def _image_to_response(image) -> dict:
    """Image dict plus self, file and schema links."""
    data = image.to_dict()
    data["self"] = f"/v2/images/{image.id}"
    data["file"] = f"/v2/images/{image.id}/file"
    data["schema"] = "/v2/schemas/image"
    return data


def _validate_body(body) -> tuple[dict, str | None]:
    """Validate a create body. Returns (kwargs for create, error message)."""
    if not isinstance(body, dict):
        return {}, "Request body must be a JSON object"
    kwargs: dict = {}
    if "id" in body:
        if not isinstance(body["id"], str):
            return {}, "'id' must be a UUID string"
        kwargs["image_id"] = body["id"]
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        return {}, "'name' must be a string"
    kwargs["name"] = name
    for key in _STR_ATTRS:
        if key in body:
            if not isinstance(body[key], str):
                return {}, f"'{key}' must be a string"
            kwargs[key] = body[key]
    for key in _INT_ATTRS:
        if key in body:
            val = body[key]
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                return {}, f"'{key}' must be a non-negative integer"
            kwargs[key] = val
    if "tags" in body:
        tags = body["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return {}, "'tags' must be a list of strings"
        kwargs["tags"] = list(tags)
    return kwargs, None


@image_bp.route("/v2/images", methods=["POST"])
@require_token
def create_image():
    """Create an image (metadata only, immediately active)."""
    kwargs, err = _validate_body(request.get_json(silent=True))
    if err:
        return _error(400, err)
    try:
        image = get_simulator().image_manager.create(**kwargs)
    except ValueError as exc:
        return _error(400, str(exc))
    except DuplicateResourceError as exc:
        return _error(409, str(exc))
    resp = jsonify(_image_to_response(image))
    resp.status_code = 201
    return resp


@image_bp.route("/v2/images", methods=["GET"])
@require_token
def list_images():
    """List images, optionally filtered by name and status."""
    images = get_simulator().image_manager.list(
        name=request.args.get("name"), status=request.args.get("status")
    )
    return jsonify({
        "images": [_image_to_response(i) for i in images],
        "schema": "/v2/schemas/images",
        "first": "/v2/images",
    })


@image_bp.route("/v2/images/<image_id>", methods=["GET"])
@require_token
def get_image(image_id):
    """Show an image."""
    image = get_simulator().image_manager.get(image_id)
    if image is None:
        return _error(404, f"Image {image_id} not found")
    return jsonify(_image_to_response(image))


@image_bp.route("/v2/images/<image_id>", methods=["DELETE"])
@require_token
def delete_image(image_id):
    """Delete an image."""
    try:
        get_simulator().image_manager.delete(image_id)
    except ResourceNotFoundError:
        return _error(404, f"Image {image_id} not found")
    return make_response("", 204)


@image_bp.route("/v2/images/<image_id>", methods=["PATCH"])
@require_token
def patch_image(image_id):
    """Image update is not supported."""
    return _error(405, "PATCH is not supported on images")


@image_bp.route("/v2/images/<image_id>/file", methods=["PUT", "GET"])
@require_token
def image_file(image_id):
    """Image data upload and download are not supported."""
    return _error(405, f"{request.method} is not supported on image files")
