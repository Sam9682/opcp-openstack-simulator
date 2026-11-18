"""Canonical error messages (Requirement 20) and envelope renderers.

Each canonical string is defined exactly once, here.
"""

import json
from typing import Any, Dict, Optional


def no_valid_host() -> str:
    return "No valid host was found. There are not enough hosts available."


def invalid_availability_zone(zone_uuid: str) -> str:
    return f"Invalid availability zone: [nova::{zone_uuid}]"


def flavor_not_found(flavor_id: str) -> str:
    return f"Flavor {flavor_id} could not be found."


def flavor_not_accessible(flavor_id: str, project: str) -> str:
    return f"Flavor {flavor_id} is not accessible to project {project}."


def image_not_found(image_id: str) -> str:
    return f"Image {image_id} could not be found."


def image_not_active(image_id: str) -> str:
    return f"Image {image_id} is not active."


def keypair_not_found(name: str, user: str) -> str:
    return f"Keypair {name} not found for user {user}."


def security_group_not_found(group_id: str, project: str) -> str:
    return f"Security group {group_id} not found for project {project}."


def quota_exceeded(resource: str, requested: int, used: int, limit: int) -> str:
    return (
        f"Quota exceeded for {resource}: Requested {requested}, "
        f"but already used {used} of {limit}."
    )


def node_locked(node_uuid: str) -> str:
    return f"Node {node_uuid} is locked"


def node_not_provided(node_uuid: str) -> str:
    return f"Node {node_uuid} is not in a state that can be provided"


def invalid_state(state: str, node_uuid: str) -> str:
    return f"Invalid state {state} for node {node_uuid}"


def not_authorized(node_uuid: str) -> str:
    return f"Not authorized to deploy on node {node_uuid}"


def admin_required() -> str:
    return "Admin privileges are required for this operation"


def deploy_failed(last_error: Optional[str]) -> str:
    return f"Deploy failed: {last_error}"


# --- Envelope renderers -------------------------------------------------

# HTTP status -> Compute envelope kind (used when no kind is given).
_COMPUTE_KIND_BY_STATUS = {
    400: "badRequest",
    403: "forbidden",
    404: "itemNotFound",
    409: "conflictingRequest",
    500: "computeFault",
}


def compute_envelope(
    kind: str, message: str, status: int, details: Any = None
) -> Dict[str, Any]:
    """Render a Compute error body: {kind: {message, code[, details]}}.

    ``badRequest`` always carries ``details`` (Req 20.15); ``itemNotFound``
    and ``forbidden`` carry only ``message`` and ``code``.
    """
    body: Dict[str, Any] = {"message": message, "code": status}
    if kind == "badRequest":
        body["details"] = details
    elif details is not None and kind not in ("itemNotFound", "forbidden"):
        body["details"] = details
    return {kind: body}


def compute_kind_for_status(status: int) -> str:
    return _COMPUTE_KIND_BY_STATUS.get(status, "computeFault")


def ironic_envelope(message: str) -> Dict[str, str]:
    """Render a Baremetal error body (Req 20.16)."""
    return {
        "error_message": json.dumps(
            {"faultcode": "Client", "faultstring": message, "debuginfo": None}
        )
    }


# --- Server creation validation messages ---------------------------------


def baremetal_flavor_no_hw() -> str:
    return "baremetal flavor cannot set hw:*"


def image_requires_kernel_ramdisk() -> str:
    return "image requires kernel and ramdisk"


def invalid_trait_spec_value() -> str:
    return "Invalid value for trait extra spec"


def invalid_resource_class_spec(key: str) -> str:
    return f"Invalid value for extra spec {key}: must be 1"


def missing_resource_class_spec() -> str:
    return "baremetal flavor requires a resources:CUSTOM_<CLASS>=1 extra spec"


def network_not_found(network_id: str) -> str:
    return f"Network {network_id} could not be found."


def server_group_invalid(group_id: str) -> str:
    return f"Server group {group_id} is not available to the project."


def project_mismatch() -> str:
    return "Policy doesn't allow creating a server in another project."


def instance_locked() -> str:
    return "Instance is locked"


def node_hint(node_uuid: str, state: str) -> str:
    return (
        f"Node {node_uuid} is in provision_state '{state}' and is the only "
        "candidate; it must be 'available' to be scheduled."
    )
