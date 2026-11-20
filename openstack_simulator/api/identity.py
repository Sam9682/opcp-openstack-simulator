"""Keystone Identity API v3 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import (
    get_simulator,
    get_base_url,
    require_token,
    build_service_catalog,
)
from openstack_simulator.exceptions import (
    AuthenticationError,
    TokenExpiredError,
    ResourceNotFoundError,
)
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


def _extract_credentials(data: dict) -> tuple[str, str, str]:
    """Return ``(auth_type, username, password)`` from a token request body.

    ``auth_type`` is ``application_credential``, ``password`` or ``unknown``.
    """
    identity = data.get("auth", {}).get("identity", {})
    methods = identity.get("methods", [])

    if "application_credential" in methods or "application_credential" in identity:
        app_cred = identity.get("application_credential", {})
        username = app_cred.get("name", "") or app_cred.get("id", "")
        return "application_credential", username, app_cred.get("secret", "")

    if "password" in methods or "password" in identity:
        user = identity.get("password", {}).get("user", {})
        username = user.get("name", "") or user.get("id", "")
        return "password", username, user.get("password", "")

    user = identity.get("user", {})
    if user:
        return "password", user.get("name", "") or user.get("id", ""), user.get("password", "")
    return "unknown", identity.get("name", ""), identity.get("password", "")


def _token_project(sim) -> dict:
    return {
        "domain": {
            "id": current_app.config["DOMAIN_ID"],
            "name": current_app.config["DOMAIN_NAME"],
        },
        "id": sim.project_id,
        "name": sim.project_name,
    }


@identity_bp.route("/v3/auth/tokens", methods=["POST"])
def create_token():
    """Authenticate and issue a token.

    Application credentials authenticate against their own isolated
    environment: the credential ID selects the environment and the secret must
    be the SHA-256 hex digest of that ID. Password authentication issues a
    token in the default environment.
    """
    registry = current_app.config["ENVIRONMENTS"]
    data = request.get_json(silent=True) or {}
    auth_type, username, password = _extract_credentials(data)
    identity = data.get("auth", {}).get("identity", {})
    methods = identity.get("methods", []) or [auth_type if auth_type != "unknown" else "password"]

    if not username or not password:
        return jsonify({
            "error": {"message": "Username and password must not be empty", "code": 400}
        }), 400

    if auth_type == "application_credential":
        try:
            token, sim = registry.authenticate(username, password)
        except AuthenticationError as e:
            return jsonify({"error": {"message": str(e), "code": 401}}), 401
    else:
        sim = registry.default
        try:
            token = sim.auth_manager.authenticate(username, password)
        except AuthenticationError as e:
            return jsonify({"error": {"message": str(e), "code": 401}}), 401

    base_url = get_base_url()
    domain_id = current_app.config["DOMAIN_ID"]
    domain_name = current_app.config["DOMAIN_NAME"]

    response_body = {
        "token": {
            "methods": methods,
            "user": {
                "domain": {"id": domain_id, "name": domain_name},
                "id": _generate_id(),
                "name": username,
                "password_expires_at": None,
            },
            "audit_ids": [_generate_id()[:20]],
            "expires_at": token.expires_at,
            "issued_at": token.issued_at,
            "project": _token_project(sim),
            "roles": [
                {"id": _generate_id(), "name": "admin"},
                {"id": _generate_id(), "name": "member"},
            ],
            "catalog": build_service_catalog(base_url, sim.project_id),
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
            "project": _token_project(sim),
            "roles": [
                {"id": _generate_id(), "name": "admin"},
                {"id": _generate_id(), "name": "member"},
            ],
            "catalog": build_service_catalog(base_url, sim.project_id),
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


def _project_dict(base_url: str, sim) -> dict:
    """Build the project owned by ``sim``'s credential."""
    domain_id = current_app.config["DOMAIN_ID"]
    return {
        "id": sim.project_id,
        "name": sim.project_name,
        "domain_id": domain_id,
        "enabled": True,
        "description": f"Environment of application credential '{sim.credential_id}'",
        "parent_id": domain_id,
        "is_domain": False,
        "links": {"self": f"{base_url}/identity/v3/projects/{sim.project_id}"},
    }


@identity_bp.route("/v3/projects", methods=["GET"])
@require_token
def list_projects():
    """List the projects of the caller's environment."""
    base_url = get_base_url()
    sim = get_simulator()
    return jsonify({
        "projects": [_project_dict(base_url, sim)],
        "links": {
            "self": f"{base_url}/identity/v3/projects",
            "previous": None,
            "next": None,
        },
    })


@identity_bp.route("/v3/projects/<project_id>", methods=["GET"])
@require_token
def get_project(project_id):
    """Show a project by ID; project names are accepted too."""
    sim = get_simulator()
    if project_id not in (sim.project_id, sim.project_name):
        return jsonify({
            "error": {"message": f"Could not find project: {project_id}", "code": 404}
        }), 404
    return jsonify({"project": _project_dict(get_base_url(), sim)})
