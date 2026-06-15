"""Keystone Identity API v3 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import (
    get_simulator,
    get_base_url,
    require_token,
    build_service_catalog,
)
from openstack_simulator.exceptions import AuthenticationError, TokenExpiredError, ResourceNotFoundError
from openstack_simulator.models import _generate_id

identity_bp = Blueprint("identity", __name__, url_prefix="/identity")


@identity_bp.route("/", methods=["GET"])
@identity_bp.route("/v3/", methods=["GET"])
def version_discovery():
    """Keystone version discovery."""
    base_url = get_base_url()
    return jsonify({
        "version": {
            "id": "v3.14",
            "status": "stable",
            "updated": "2020-04-07T00:00:00Z",
            "links": [{"rel": "self", "href": f"{base_url}/identity/v3/"}],
            "media-types": [
                {"base": "application/json", "type": "application/vnd.openstack.identity-v3+json"}
            ],
        }
    })


@identity_bp.route("/v3/auth/tokens", methods=["POST"])
def create_token():
    """Authenticate and issue a token.

    Supports:
    - password authentication
    - application_credential authentication
    """
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    auth = data.get("auth", {})
    identity = auth.get("identity", {})
    methods = identity.get("methods", [])

    username = ""
    password = ""

    # Handle password authentication
    if "password" in methods:
        user_data = identity.get("password", {}).get("user", {})
        username = user_data.get("name", "") or user_data.get("id", "")
        password = user_data.get("password", "")
    # Handle application_credential authentication
    elif "application_credential" in methods:
        app_cred = identity.get("application_credential", {})
        # Treat app credential id/name as username, secret as password
        username = app_cred.get("name", "") or app_cred.get("id", "")
        password = app_cred.get("secret", "")
    # Handle direct password auth without explicit methods array (common in CLI usage)
    else:
        # Check for direct password auth format
        user_data = identity.get("password", {}).get("user", {})
        if user_data:
            username = user_data.get("name", "") or user_data.get("id", "")
            password = user_data.get("password", "")
        else:
            # Try to extract from top-level auth object
            username = identity.get("user", {}).get("name", "") or identity.get("user", {}).get("id", "")
            password = identity.get("user", {}).get("password", "")
        
        # If we still don't have username/password, check for simple format
        if not username and not password:
            # Check for simpler format that might be used by CLI tools
            username = identity.get("name", "") or identity.get("user", {}).get("name", "")
            password = identity.get("password", "") or identity.get("user", {}).get("password", "")

    # Validate that we have both username and password
    if not username or not password:
        return jsonify({"error": {"message": "Username and password must not be empty", "code": 400}}), 400

    try:
        token = sim.auth_manager.authenticate(username, password)
    except AuthenticationError as e:
        return jsonify({"error": {"message": str(e), "code": 401}}), 401

    base_url = get_base_url()
    project_id = current_app.config["PROJECT_ID"]
    domain_id = current_app.config["DOMAIN_ID"]
    domain_name = current_app.config["DOMAIN_NAME"]

    response_body = {
        "token": {
            "methods": methods if methods else ["password"],  # Ensure methods are included even if not explicitly provided
            "user": {
                "domain": {"id": domain_id, "name": domain_name},
                "id": _generate_id(),
                "name": username,
                "password_expires_at": None,
            },
            "audit_ids": [_generate_id()[:20]],
            "expires_at": token.expires_at,
            "issued_at": token.issued_at,
            "project": {
                "domain": {"id": domain_id, "name": domain_name},
                "id": project_id,
                "name": "simulator-project",
            },
            "roles": [
                {"id": _generate_id(), "name": "admin"},
                {"id": _generate_id(), "name": "member"},
            ],
            "catalog": build_service_catalog(base_url),
        }
    }

    resp = jsonify(response_body)
    resp.status_code = 201
    resp.headers["X-Subject-Token"] = token.id
    return resp


@identity_bp.route("/v3/auth/tokens", methods=["GET"])
def validate_token():
    """Validate a token (GET with X-Subject-Token header)."""
    sim = get_simulator()
    subject_token = request.headers.get("X-Subject-Token")
    if not subject_token:
        return jsonify({"error": {"message": "X-Subject-Token header required", "code": 400}}), 400

    try:
        sim.auth_manager.validate_token(subject_token)
    except ResourceNotFoundError:
        return jsonify({"error": {"message": "Token not found", "code": 404}}), 404
    except TokenExpiredError:
        return jsonify({"error": {"message": "Token expired", "code": 401}}), 401

    token_obj = sim.store.tokens.get(subject_token)
    base_url = get_base_url()
    project_id = current_app.config["PROJECT_ID"]
    domain_id = current_app.config["DOMAIN_ID"]
    domain_name = current_app.config["DOMAIN_NAME"]

    return jsonify({
        "token": {
            "methods": ["password"],
            "user": {
                "domain": {"id": domain_id, "name": domain_name},
                "id": _generate_id(),
                "name": token_obj.username,
            },
            "expires_at": token_obj.expires_at,
            "issued_at": token_obj.issued_at,
            "project": {
                "domain": {"id": domain_id, "name": domain_name},
                "id": project_id,
                "name": "simulator-project",
            },
            "roles": [
                {"id": _generate_id(), "name": "admin"},
                {"id": _generate_id(), "name": "member"},
            ],
            "catalog": build_service_catalog(base_url),
        }
    })


@identity_bp.route("/v3/auth/tokens", methods=["HEAD"])
def check_token():
    """Check token validity (HEAD request, returns 200 or 404)."""
    sim = get_simulator()
    subject_token = request.headers.get("X-Subject-Token")
    if not subject_token:
        return "", 400

    try:
        sim.auth_manager.validate_token(subject_token)
    except (ResourceNotFoundError, TokenExpiredError):
        return "", 404

    return "", 200