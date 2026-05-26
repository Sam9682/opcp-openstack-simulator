"""Neutron Network API v2.0 endpoints."""

from __future__ import annotations

from flask import Blueprint, request, jsonify, current_app

from openstack_simulator.api.helpers import get_simulator, require_token
from openstack_simulator.exceptions import (
    DuplicateResourceError,
    ResourceLimitExceededError,
    ResourceNotFoundError,
)

network_bp = Blueprint("network", __name__, url_prefix="/network")


# --- Networks ---

@network_bp.route("/v2.0/networks", methods=["GET"])
@require_token
def list_networks():
    """List all networks."""
    sim = get_simulator()
    networks = sim.network_manager.list()
    return jsonify({"networks": [_network_to_dict(n) for n in networks]})


@network_bp.route("/v2.0/networks", methods=["POST"])
@require_token
def create_network():
    """Create a network."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    net_data = data.get("network", {})
    name = net_data.get("name", "")

    if not name:
        return jsonify({"NeutronError": {"message": "Network name is required", "type": "BadRequest"}}), 400

    try:
        network = sim.network_manager.create(name)
    except ResourceLimitExceededError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "OverQuota"}}), 409
    except DuplicateResourceError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "Conflict"}}), 409

    return jsonify({"network": _network_to_dict(network)}), 201


@network_bp.route("/v2.0/networks/<network_id>", methods=["GET"])
@require_token
def get_network(network_id: str):
    """Get a network by ID or name."""
    sim = get_simulator()
    network = _find_network(sim, network_id)
    if network is None:
        return jsonify({"NeutronError": {"message": f"Network {network_id} not found", "type": "NetworkNotFound"}}), 404

    return jsonify({"network": _network_to_dict(network)})


@network_bp.route("/v2.0/networks/<network_id>", methods=["DELETE"])
@require_token
def delete_network(network_id: str):
    """Delete a network."""
    sim = get_simulator()
    network = _find_network(sim, network_id)
    if network is None:
        return jsonify({"NeutronError": {"message": f"Network {network_id} not found", "type": "NetworkNotFound"}}), 404

    try:
        sim.network_manager.delete(network.name)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NetworkNotFound"}}), 404

    return "", 204


# --- Subnets ---

@network_bp.route("/v2.0/subnets", methods=["GET"])
@require_token
def list_subnets():
    """List all subnets."""
    sim = get_simulator()
    subnets = sim.store.list_active("subnets")
    return jsonify({"subnets": [_subnet_to_dict(s) for s in subnets]})


@network_bp.route("/v2.0/subnets", methods=["POST"])
@require_token
def create_subnet():
    """Create a subnet."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    subnet_data = data.get("subnet", {})

    network_id = subnet_data.get("network_id", "")
    name = subnet_data.get("name", "")
    cidr = subnet_data.get("cidr", "")
    gateway_ip = subnet_data.get("gateway_ip", "")

    # Find network by ID
    network = _find_network(sim, network_id)
    if network is None:
        return jsonify({"NeutronError": {"message": f"Network {network_id} not found", "type": "NetworkNotFound"}}), 404

    try:
        subnet = sim.network_manager.create_subnet(network.name, name, cidr, gateway_ip)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NetworkNotFound"}}), 404

    return jsonify({"subnet": _subnet_to_dict(subnet)}), 201


# --- Routers ---

@network_bp.route("/v2.0/routers", methods=["GET"])
@require_token
def list_routers():
    """List all routers."""
    sim = get_simulator()
    routers = sim.store.list_active("routers")
    return jsonify({"routers": [_router_to_dict(r) for r in routers]})


@network_bp.route("/v2.0/routers", methods=["POST"])
@require_token
def create_router():
    """Create a router."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    router_data = data.get("router", {})
    name = router_data.get("name", "")

    router = sim.network_manager.create_router(name)
    return jsonify({"router": _router_to_dict(router)}), 201


@network_bp.route("/v2.0/routers/<router_id>/add_router_interface", methods=["PUT"])
@require_token
def add_router_interface(router_id: str):
    """Add an interface (subnet) to a router."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    subnet_id = data.get("subnet_id", "")

    # Find router by ID or name
    router = _find_router(sim, router_id)
    if router is None:
        return jsonify({"NeutronError": {"message": f"Router {router_id} not found", "type": "RouterNotFound"}}), 404

    try:
        sim.network_manager.add_router_interface(router.name, subnet_id)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NotFound"}}), 404

    return jsonify({"subnet_id": subnet_id, "port_id": "simulated-port-id"})


# --- Ports ---

@network_bp.route("/v2.0/ports", methods=["GET"])
@require_token
def list_ports():
    """List all ports."""
    sim = get_simulator()
    ports = sim.store.list_active("ports")
    return jsonify({"ports": [_port_to_dict(p) for p in ports]})


@network_bp.route("/v2.0/ports", methods=["POST"])
@require_token
def create_port():
    """Create a port."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    port_data = data.get("port", {})

    network_id = port_data.get("network_id", "")
    name = port_data.get("name", "")

    # Find network by ID
    network = _find_network(sim, network_id)
    if network is None:
        return jsonify({"NeutronError": {"message": f"Network {network_id} not found", "type": "NetworkNotFound"}}), 404

    try:
        port = sim.network_manager.create_port(network.name, name)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NetworkNotFound"}}), 404

    return jsonify({"port": _port_to_dict(port)}), 201


# --- Security Groups ---

@network_bp.route("/v2.0/security-groups", methods=["GET"])
@require_token
def list_security_groups():
    """List all security groups."""
    sim = get_simulator()
    sgs = sim.security_group_manager.list()
    return jsonify({"security_groups": [_sg_to_dict(sg) for sg in sgs]})


@network_bp.route("/v2.0/security-groups", methods=["POST"])
@require_token
def create_security_group():
    """Create a security group."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    sg_data = data.get("security_group", {})
    name = sg_data.get("name", "")
    description = sg_data.get("description", "")

    try:
        sg = sim.security_group_manager.create(name, description)
    except ResourceLimitExceededError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "OverQuota"}}), 409
    except DuplicateResourceError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "Conflict"}}), 409

    return jsonify({"security_group": _sg_to_dict(sg)}), 201


@network_bp.route("/v2.0/security-groups/<sg_id>", methods=["GET"])
@require_token
def get_security_group(sg_id: str):
    """Get a security group by ID or name."""
    sim = get_simulator()
    sg = _find_security_group(sim, sg_id)
    if sg is None:
        return jsonify({"NeutronError": {"message": f"Security group {sg_id} not found", "type": "NotFound"}}), 404

    return jsonify({"security_group": _sg_to_dict(sg)})


@network_bp.route("/v2.0/security-groups/<sg_id>", methods=["DELETE"])
@require_token
def delete_security_group(sg_id: str):
    """Delete a security group."""
    sim = get_simulator()
    sg = _find_security_group(sim, sg_id)
    if sg is None:
        return jsonify({"NeutronError": {"message": f"Security group {sg_id} not found", "type": "NotFound"}}), 404

    try:
        sim.security_group_manager.delete(sg.name)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NotFound"}}), 404

    return "", 204


@network_bp.route("/v2.0/security-group-rules", methods=["POST"])
@require_token
def create_security_group_rule():
    """Add a rule to a security group."""
    sim = get_simulator()
    data = request.get_json(silent=True) or {}
    rule_data = data.get("security_group_rule", {})

    sg_id = rule_data.get("security_group_id", "")
    protocol = rule_data.get("protocol", "")
    port_range_min = rule_data.get("port_range_min")
    port_range_max = rule_data.get("port_range_max")
    direction = rule_data.get("direction", "ingress")
    remote_ip_prefix = rule_data.get("remote_ip_prefix", "0.0.0.0/0")

    # Build port_range string
    if port_range_min and port_range_max:
        port_range = f"{port_range_min}:{port_range_max}"
    else:
        port_range = ""

    # Find SG by ID
    sg = _find_security_group(sim, sg_id)
    if sg is None:
        return jsonify({"NeutronError": {"message": f"Security group {sg_id} not found", "type": "NotFound"}}), 404

    try:
        rule = sim.security_group_manager.add_rule(sg.name, protocol, port_range, direction, remote_ip_prefix)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NotFound"}}), 404

    return jsonify({"security_group_rule": _rule_to_dict(rule)}), 201


@network_bp.route("/v2.0/security-group-rules/<rule_id>", methods=["DELETE"])
@require_token
def delete_security_group_rule(rule_id: str):
    """Delete a security group rule."""
    sim = get_simulator()
    try:
        sim.security_group_manager.delete_rule(rule_id)
    except ResourceNotFoundError as e:
        return jsonify({"NeutronError": {"message": str(e), "type": "NotFound"}}), 404

    return "", 204


# --- Helpers ---

def _network_to_dict(network) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    return {
        "id": network.id,
        "name": network.name,
        "status": network.status,
        "subnets": network.subnet_ids,
        "tenant_id": project_id,
        "admin_state_up": True,
        "shared": False,
        "router:external": False,
        "provider:network_type": "flat",
    }


def _subnet_to_dict(subnet) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    return {
        "id": subnet.id,
        "name": subnet.name,
        "network_id": subnet.network_id,
        "cidr": subnet.cidr,
        "gateway_ip": subnet.gateway,
        "ip_version": 4,
        "tenant_id": project_id,
        "enable_dhcp": True,
        "allocation_pools": [],
    }


def _router_to_dict(router) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    return {
        "id": router.id,
        "name": router.name,
        "status": router.status,
        "tenant_id": project_id,
        "admin_state_up": True,
        "external_gateway_info": None,
    }


def _port_to_dict(port) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    return {
        "id": port.id,
        "name": port.name,
        "network_id": port.network_id,
        "mac_address": port.mac_address,
        "status": port.status,
        "tenant_id": project_id,
        "admin_state_up": True,
        "fixed_ips": [],
    }


def _sg_to_dict(sg) -> dict:
    project_id = current_app.config["PROJECT_ID"]
    return {
        "id": sg.id,
        "name": sg.name,
        "description": sg.description,
        "tenant_id": project_id,
        "security_group_rules": [_rule_to_dict(r) for r in sg.rules],
    }


def _rule_to_dict(rule) -> dict:
    parts = rule.port_range.split(":") if rule.port_range else [None, None]
    port_min = int(parts[0]) if parts[0] else None
    port_max = int(parts[1]) if len(parts) > 1 and parts[1] else None

    return {
        "id": rule.id,
        "security_group_id": rule.security_group_id,
        "protocol": rule.protocol,
        "port_range_min": port_min,
        "port_range_max": port_max,
        "direction": rule.direction,
        "remote_ip_prefix": rule.remote_ip_prefix,
        "ethertype": "IPv4",
    }


def _find_network(sim, identifier: str):
    """Find a network by ID or name."""
    network = sim.network_manager.get(identifier)
    if network:
        return network
    for net in sim.network_manager.list():
        if net.id == identifier:
            return net
    return None


def _find_router(sim, identifier: str):
    """Find a router by ID or name."""
    router = sim.store.get("routers", identifier)
    if router:
        return router
    for r in sim.store.list_active("routers"):
        if r.id == identifier:
            return r
    return None


def _find_security_group(sim, identifier: str):
    """Find a security group by ID or name."""
    sg = sim.security_group_manager.get(identifier)
    if sg:
        return sg
    for s in sim.security_group_manager.list():
        if s.id == identifier:
            return s
    return None
