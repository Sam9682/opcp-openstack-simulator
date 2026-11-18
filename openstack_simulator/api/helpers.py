"""Shared helpers for the API layer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import wraps
from flask import request, jsonify, current_app, g

from openstack_simulator import messages
from openstack_simulator.clock import Clock
from openstack_simulator.exceptions import (
    AuthenticationError,
    BadRequest,
    SimError,
    TokenExpiredError,
    ResourceNotFoundError,
    render_error,
)

DEFAULT_MICROVERSION = (2, 1)
LATEST_MICROVERSION = (2, 96)
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")


@dataclass(frozen=True)
class CallerContext:
    """Per-request caller data handed to the service layer."""

    project_id: str
    is_admin: bool
    now: float
    microversion: tuple = DEFAULT_MICROVERSION


def parse_microversion(headers) -> tuple:
    """Parse the Compute microversion from request headers.

    ``OpenStack-API-Version: compute 2.78`` and ``X-OpenStack-Nova-API-Version: 2.78``
    are accepted; ``latest`` maps to LATEST_MICROVERSION. A service-prefixed
    header for another service is ignored. Raises BadRequest if malformed.
    """
    value = headers.get("OpenStack-API-Version")
    if value is not None:
        parts = value.split()
        if len(parts) == 2:
            value = parts[1] if parts[0].lower() == "compute" else None
        elif len(parts) == 1:
            value = parts[0]
        else:
            raise BadRequest(f"Invalid microversion: {value!r}")
    if value is None:
        value = headers.get("X-OpenStack-Nova-API-Version")
    if value is None:
        return DEFAULT_MICROVERSION
    value = value.strip()
    if value.lower() == "latest":
        return LATEST_MICROVERSION
    m = _VERSION_RE.match(value)
    if not m:
        raise BadRequest(f"Invalid microversion: {value!r}")
    return (int(m.group(1)), int(m.group(2)))


def build_caller_context(token_id: str) -> CallerContext:
    """Build the CallerContext for the current request.

    ``now`` comes from the ``now`` query parameter (wins) or ``X-Sim-Now``,
    otherwise from the simulator clock. Raises InvalidTimestamp (400).
    """
    sim = current_app.config["SIMULATOR"]
    raw = request.args.get("now")
    if raw is None:
        raw = request.headers.get("X-Sim-Now")
    override = Clock.parse(raw) if raw is not None else None
    now = sim.clock.now(override)
    token = sim.store.tokens.get(token_id)
    project_id = getattr(token, "project_id", None) or current_app.config["PROJECT_ID"]
    roles = getattr(token, "roles", None) or []
    return CallerContext(
        project_id=project_id,
        is_admin="admin" in roles,
        now=now,
        microversion=parse_microversion(request.headers),
    )


def register_error_handlers(app) -> None:
    """Render SimError as the Compute or Ironic envelope by blueprint."""

    @app.errorhandler(SimError)
    def _handle_sim_error(err: SimError):
        if request.blueprint == "baremetal" and err.kind != "ironic":
            body = messages.ironic_envelope(err.message)
        else:
            body = render_error(err)
        return jsonify(body), err.status


def get_simulator():
    """Get the Simulator instance from the Flask app config."""
    return current_app.config["SIMULATOR"]


def get_base_url() -> str:
    """Build the base URL from the current request."""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    return f"{scheme}://{request.host}"


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

        g.caller_context = build_caller_context(token_id)
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