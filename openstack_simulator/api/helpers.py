"""Shared helpers for the API layer."""

from __future__ import annotations

from functools import wraps
from flask import request, jsonify, current_app

from openstack_simulator.exceptions import (
    AuthenticationError,
    TokenExpiredError,
    ResourceNotFoundError,
)


def get_simulator():
    """Get the Simulator instance from the Flask app config."""
    return current_app.config["SIMULATOR"]


def get_base_url() -> str:
    """Build the base URL from the current request."""
    return request.host_url.rstrip("/")


def require_token(f):
    """Decorator that validates the X-Auth-Token header."""

    @wraps(f)
    def decorated(*args, **kwargs):
        token_id = request.headers.get("X-Auth-Token")
        if not token_id:
            return jsonify({"error": {"message": "Authentication required", "code": 401}}), 401

        sim = get_simulator()
        try:
            sim.auth_manager.validate_token(token_id)
        except (ResourceNotFoundError, TokenExpiredError):
            return jsonify({"error": {"message": "Invalid or expired token", "code": 401}}), 401

        return f(*args, **kwargs)

    return decorated


def build_service_catalog(base_url: str) -> list[dict]:
    """Build a minimal service catalog for the token response."""
    project_id = current_app.config["PROJECT_ID"]
    region = current_app.config["REGION"]

    services = [
        {
            "type": "identity",
            "id": "identity-service-id",
            "name": "keystone",
            "endpoints": [
                {"id": "id-pub", "interface": "public", "region_id": region, "url": f"{base_url}/identity", "region": region},
                {"id": "id-int", "interface": "internal", "region_id": region, "url": f"{base_url}/identity", "region": region},
                {"id": "id-adm", "interface": "admin", "region_id": region, "url": f"{base_url}/identity", "region": region},
            ],
        },
        {
            "type": "compute",
            "id": "compute-service-id",
            "name": "nova",
            "endpoints": [
                {"id": "c-pub", "interface": "public", "region_id": region, "url": f"{base_url}/compute/v2.1", "region": region},
                {"id": "c-int", "interface": "internal", "region_id": region, "url": f"{base_url}/compute/v2.1", "region": region},
            ],
        },
        {
            "type": "network",
            "id": "network-service-id",
            "name": "neutron",
            "endpoints": [
                {"id": "n-pub", "interface": "public", "region_id": region, "url": f"{base_url}/network", "region": region},
                {"id": "n-int", "interface": "internal", "region_id": region, "url": f"{base_url}/network", "region": region},
            ],
        },
        {
            "type": "volumev3",
            "id": "volume-service-id",
            "name": "cinder",
            "endpoints": [
                {"id": "v-pub", "interface": "public", "region_id": region, "url": f"{base_url}/volume/v3/{project_id}", "region": region},
                {"id": "v-int", "interface": "internal", "region_id": region, "url": f"{base_url}/volume/v3/{project_id}", "region": region},
            ],
        },
        {
            "type": "baremetal",
            "id": "baremetal-service-id",
            "name": "ironic",
            "endpoints": [
                {"id": "bm-pub", "interface": "public", "region_id": region, "url": f"{base_url}/baremetal/v1", "region": region},
                {"id": "bm-int", "interface": "internal", "region_id": region, "url": f"{base_url}/baremetal/v1", "region": region},
            ],
        },
        {
            "type": "image",
            "id": "image-service-id",
            "name": "glance",
            "endpoints": [
                {"id": "i-pub", "interface": "public", "region_id": region, "url": f"{base_url}/image/v2", "region": region},
                {"id": "i-int", "interface": "internal", "region_id": region, "url": f"{base_url}/image/v2", "region": region},
                {"id": "i-adm", "interface": "admin", "region_id": region, "url": f"{base_url}/image/v2", "region": region},
            ],
        },
    ]
    return services