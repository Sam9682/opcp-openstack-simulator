"""Nova Compute API v2.1 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, g

from openstack_simulator.api.helpers import (
    current_project_id,
    get_simulator,
    require_token,
)
from openstack_simulator.exceptions import (
    BadRequest,
    Conflict,
    DuplicateResourceError,
    Forbidden,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)
from openstack_simulator.managers.quota import QUOTA_RESOURCES
from openstack_simulator.managers.scheduler import flavor_resource_class
from openstack_simulator.managers.server_service import validate_flavor_extra_specs
from openstack_simulator.models import Flavor, _generate_id

compute_bp = Blueprint("compute", __name__, url_prefix="/compute/v2.1")


def _ctx():
    """CallerContext of the current request."""
    return g.caller_context


def _instance_to_server(instance, project_id: str) -> dict:
    """Convert an Instance model to a Nova server response dict."""
    server = {
        "id": instance.id,
        "name": instance.name,
        "status": instance.status,
        "tenant_id": getattr(instance, "project_id", None) or project_id,
        "user_id": "fake-user-id",
        "flavor": {"id": instance.flavor, "links": []},
        "image": {"id": instance.image, "links": []},
        "created": instance.created_at,
        "updated": instance.created_at,
        "addresses": {},
        "links": [],
        "OS-EXT-STS:task_state": getattr(instance, "task_state", None),
        "OS-EXT-STS:vm_state": instance.status.lower() if instance.status != "DELETED" else "deleted",
        "OS-EXT-STS:power_state": 1 if instance.status == "ACTIVE" else 0,
        "os-extended-volumes:volumes_attached": [],
        "metadata": {},
    }
    if getattr(instance, "node_id", None):
        server["OS-EXT-SRV-ATTR:hypervisor_hostname"] = instance.node_id
    if getattr(instance, "fault", None):
        server["fault"] = instance.fault
    return server


def _refresh(sim, instances):
    """Sync nodes, then refresh bare-metal servers (status derived from node)."""
    if any(getattr(i, "node_id", None) for i in instances):
        sim.node_service.sync(_ctx().now)
        for i in instances:
            sim.server_service.refresh(i)
    return instances


def _visible(instance) -> bool:
    ctx = _ctx()
    return ctx.is_admin or getattr(instance, "project_id", None) in (None, ctx.project_id)


@compute_bp.route("/servers", methods=["GET"])
@require_token
def list_servers():
    """List all servers (instances)."""
    sim = get_simulator()
    project_id = current_project_id()
    instances = [i for i in sim.compute_manager.list() if _visible(i)]
    _refresh(sim, instances)
    instances = [i for i in instances if i.status != "DELETED"]
    servers = [_instance_to_server(i, project_id) for i in instances]
    return jsonify({"servers": servers})


@compute_bp.route("/servers/detail", methods=["GET"])
@require_token
def list_servers_detail():
    """List all servers with full details."""
    sim = get_simulator()
    project_id = current_project_id()
    instances = [i for i in sim.compute_manager.list() if _visible(i)]
    _refresh(sim, instances)
    servers = [_instance_to_server(i, project_id) for i in instances]
    return jsonify({"servers": servers})


DEFAULT_RESOURCE_CLASS = "CUSTOM_BAREMETAL"


def _baremetal_flavor(sim, flavor_ref):
    """Return the flavor to schedule on baremetal nodes.

    Every flavor is scheduled onto baremetal nodes, so this returns the
    resolved flavor. A flavor without a ``resources:CUSTOM_<CLASS>=1``
    extra spec uses ``DEFAULT_RESOURCE_CLASS`` (``CUSTOM_BAREMETAL``), the
    class Ironic maps node class ``baremetal`` to.
    """
    flavors = sim.store.flavors
    flavor = flavors.get(flavor_ref)
    if flavor is None:
        flavor = next((f for f in flavors.values() if f.name == flavor_ref), None)
    return flavor


@compute_bp.route("/servers", methods=["POST"])
@require_token
def create_server():
    """Create a new server (instance)."""
    sim = get_simulator()
    project_id = current_project_id()
    data = request.get_json(silent=True) or {}
    server_data = data.get("server", {})

    name = server_data.get("name", "")
    flavor_ref = server_data.get("flavorRef", sim.config.get("default_flavor", "m1.small"))
    image_ref = server_data.get("imageRef", sim.config.get("default_image", "ubuntu-22.04"))

    if not name:
        return jsonify({"badRequest": {"message": "Server name is required", "code": 400}}), 400

    if isinstance(flavor_ref, str) and _baremetal_flavor(sim, flavor_ref) is not None:
        body = {
            k: server_data[k]
            for k in (
                "name", "flavorRef", "imageRef", "key_name", "security_groups",
                "networks", "availability_zone", "user_data", "metadata", "traits",
                "block_device_mapping_v2", "config_drive", "project_id", "tenant_id",
                "scheduler_hints",
            )
            if k in server_data
        }
        if "scheduler_hints" not in body and "os:scheduler_hints" in data:
            body["scheduler_hints"] = data["os:scheduler_hints"]
        if "imageRef" not in body:
            body["imageRef"] = ""
        instance = sim.server_service.create(_ctx(), body)
        server = _instance_to_server(instance, project_id)
        server["adminPass"] = "simulated-password"
        return jsonify({"server": server}), 202

    if flavor_ref is not None:
        raise FlavorNotFound(messages.flavor_not_found(flavor_ref))

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
    project_id = current_project_id()

    # Try by ID first, then by name
    instance = _find_instance(sim, server_id)
    if instance is None or not _visible(instance):
        return jsonify({"itemNotFound": {"message": f"Instance {server_id} not found", "code": 404}}), 404

    _refresh(sim, [instance])
    return jsonify({"server": _instance_to_server(instance, project_id)})


def _force_requested() -> bool:
    value = request.args.get("force")
    if value is None:
        body = request.get_json(silent=True)
        value = body.get("force") if isinstance(body, dict) else None
    return str(value).lower() in ("true", "1")


@compute_bp.route("/servers/<server_id>", methods=["DELETE"])
@require_token
def delete_server(server_id: str):
    """Delete a server."""
    sim = get_simulator()
    instance = _find_instance(sim, server_id)
    if instance is None or not _visible(instance):
        # A repeated delete of a bare-metal server is idempotent (204).
        for s in list(sim.store.instances.values()):
            if (
                s.id == server_id
                and s.status == "DELETED"
                and getattr(s, "node_id", None)
                and _visible(s)
            ):
                return "", 204
        return jsonify({"itemNotFound": {"message": f"Instance {server_id} not found", "code": 404}}), 404

    if getattr(instance, "node_id", None):
        sim.server_service.delete(_ctx(), instance.id, force=_force_requested())
        return "", 204

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


# ---------------------------------------------------------------------------
# Flavors
# ---------------------------------------------------------------------------


def _flavor_to_dict(flavor: Flavor) -> dict:
    out = {
        "id": flavor.id,
        "name": flavor.name,
        "ram": flavor.ram,
        "vcpus": flavor.vcpus,
        "disk": flavor.disk,
    }
    if flavor.extra_specs:
        out["extra_specs"] = dict(flavor.extra_specs)
    if not flavor.is_public:
        out["os-flavor-access:is_public"] = False
    return out


def _flavor_listed(flavor: Flavor) -> bool:
    ctx = _ctx()
    if flavor.is_public or ctx.is_admin:
        return True
    sim = get_simulator()
    allowed = set(flavor.access) | set(sim.store.flavor_access.get(flavor.id, ()))
    return ctx.project_id in allowed


def _require_admin() -> None:
    if not _ctx().is_admin:
        raise Forbidden("Policy doesn't allow this action to be performed.")


def _find_flavor(sim, ref: str):
    flavors = sim.store.flavors
    flavor = flavors.get(ref)
    if flavor is None:
        flavor = next((f for f in flavors.values() if f.name == ref), None)
    return flavor


def _not_found(message: str):
    return jsonify({"itemNotFound": {"message": message, "code": 404}}), 404


def _is_baremetal_spec(specs) -> bool:
    return any(
        str(k).startswith(("resources:", "trait:", "capabilities:")) for k in specs
    )


def _int_field(body: dict, key: str, minimum: int) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BadRequest(f"Invalid input for field/attribute {key}.")
    return value


@compute_bp.route("/flavors", methods=["GET"])
@compute_bp.route("/flavors/detail", methods=["GET"])
@require_token
def list_flavors():
    """List available flavors."""
    sim = get_simulator()
    flavors = [_flavor_to_dict(f) for f in sim.store.flavors.values() if _flavor_listed(f)]
    return jsonify({"flavors": flavors})


@compute_bp.route("/flavors/<flavor_id>", methods=["GET"])
@require_token
def get_flavor(flavor_id: str):
    sim = get_simulator()
    flavor = _find_flavor(sim, flavor_id)
    if flavor is None or not _flavor_listed(flavor):
        return _not_found(f"Flavor {flavor_id} could not be found.")
    return jsonify({"flavor": _flavor_to_dict(flavor)})


@compute_bp.route("/flavors", methods=["POST"])
@require_token
def create_flavor():
    """Create a flavor (admin). Extra specs are validated (Requirement 9)."""
    _require_admin()
    sim = get_simulator()
    data = request.get_json(silent=True)
    body = data.get("flavor") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        raise BadRequest("Invalid input for field/attribute flavor.")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BadRequest("Invalid input for field/attribute name.")
    ram = _int_field(body, "ram", 1)
    vcpus = _int_field(body, "vcpus", 1)
    disk = _int_field(body, "disk", 0)
    flavor_id = body.get("id")
    if flavor_id in (None, "", "auto"):
        flavor_id = _generate_id()
    elif not isinstance(flavor_id, (str, int)) or isinstance(flavor_id, bool):
        raise BadRequest("Invalid input for field/attribute id.")
    flavor_id = str(flavor_id)
    is_public = body.get("os-flavor-access:is_public", body.get("is_public", True))
    if not isinstance(is_public, bool):
        raise BadRequest("Invalid input for field/attribute os-flavor-access:is_public.")
    specs = body.get("extra_specs") or {}
    if not isinstance(specs, dict):
        raise BadRequest("Invalid input for field/attribute extra_specs.")
    specs = validate_flavor_extra_specs(
        specs, sim.sim_config, baremetal=_is_baremetal_spec(specs)
    )

    with sim.lock:
        if flavor_id in sim.store.flavors:
            raise Conflict(f"Flavor with ID {flavor_id} already exists.")
        if any(f.name == name for f in sim.store.flavors.values()):
            raise Conflict(f"Flavor with name {name} already exists.")
        flavor = Flavor(
            id=flavor_id, name=name, vcpus=vcpus, ram=ram, disk=disk,
            extra_specs=specs, is_public=is_public,
        )
        sim.store.flavors[flavor_id] = flavor
    return jsonify({"flavor": _flavor_to_dict(flavor)}), 200


@compute_bp.route("/flavors/<flavor_id>/os-extra_specs", methods=["GET"])
@require_token
def get_flavor_extra_specs(flavor_id: str):
    sim = get_simulator()
    flavor = _find_flavor(sim, flavor_id)
    if flavor is None:
        return _not_found(f"Flavor {flavor_id} could not be found.")
    return jsonify({"extra_specs": dict(flavor.extra_specs)})


@compute_bp.route("/flavors/<flavor_id>/os-extra_specs", methods=["POST"])
@require_token
def set_flavor_extra_specs(flavor_id: str):
    """Add extra specs to a flavor (admin), validated like at creation."""
    _require_admin()
    sim = get_simulator()
    data = request.get_json(silent=True)
    new = data.get("extra_specs") if isinstance(data, dict) else None
    if not isinstance(new, dict):
        raise BadRequest("Invalid input for field/attribute extra_specs.")
    with sim.lock:
        flavor = _find_flavor(sim, flavor_id)
        if flavor is None:
            return _not_found(f"Flavor {flavor_id} could not be found.")
        merged = {**flavor.extra_specs, **new}
        merged = validate_flavor_extra_specs(
            merged, sim.sim_config, baremetal=_is_baremetal_spec(merged)
        )
        flavor.extra_specs = merged
        return jsonify({"extra_specs": dict(merged)})


@compute_bp.route("/flavors/<flavor_id>/action", methods=["POST"])
@require_token
def flavor_action(flavor_id: str):
    """Flavor actions: ``addTenantAccess`` (admin)."""
    _require_admin()
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    flavor = _find_flavor(sim, flavor_id)
    if flavor is None:
        return _not_found(f"Flavor {flavor_id} could not be found.")
    if "addTenantAccess" in data:
        tenant = (data["addTenantAccess"] or {}).get("tenant")
        if not isinstance(tenant, str) or not tenant:
            raise BadRequest("Invalid input for field/attribute tenant.")
        with sim.lock:
            sim.store.flavor_access.setdefault(flavor.id, set()).add(tenant)
            access = sorted(sim.store.flavor_access[flavor.id] | set(flavor.access))
        return jsonify(
            {"flavor_access": [{"flavor_id": flavor.id, "tenant_id": t} for t in access]}
        )
    return jsonify({"badRequest": {"message": "Unknown action", "code": 400}}), 400


# ---------------------------------------------------------------------------
# Limits and quotas (both read QuotaManager.snapshot)
# ---------------------------------------------------------------------------

_LIMIT_KEYS = {
    "instances": ("maxTotalInstances", "totalInstancesUsed"),
    "cores": ("maxTotalCores", "totalCoresUsed"),
    "ram": ("maxTotalRAMSize", "totalRAMUsed"),
    "key_pairs": ("maxTotalKeypairs", None),
    "server_groups": ("maxServerGroups", "totalServerGroupsUsed"),
    "server_group_members": ("maxServerGroupMembers", None),
}


def _unlimited(limit):
    return -1 if limit is None else limit


@compute_bp.route("/limits", methods=["GET"])
@require_token
def get_limits():
    sim = get_simulator()
    snap = sim.quota_manager.snapshot(_ctx().project_id)
    absolute = {}
    for resource in QUOTA_RESOURCES:
        used, limit = snap[resource]
        max_key, used_key = _LIMIT_KEYS[resource]
        absolute[max_key] = _unlimited(limit)
        if used_key:
            absolute[used_key] = used
    return jsonify({"limits": {"rate": [], "absolute": absolute}})


@compute_bp.route("/os-quota-sets/<project>", methods=["GET"])
@compute_bp.route("/os-quota-sets/<project>/detail", methods=["GET"])
@require_token
def get_quota_set(project: str):
    sim = get_simulator()
    snap = sim.quota_manager.snapshot(project)
    if request.path.endswith("/detail"):
        quota = {"id": project}
        for resource in QUOTA_RESOURCES:
            used, limit = snap[resource]
            quota[resource] = {"in_use": used, "limit": _unlimited(limit), "reserved": 0}
    else:
        quota = {"id": project}
        for resource in QUOTA_RESOURCES:
            quota[resource] = _unlimited(snap[resource][1])
    return jsonify({"quota_set": quota})


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
