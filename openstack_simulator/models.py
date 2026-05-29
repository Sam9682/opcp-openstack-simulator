"""Data models for the OpenStack Simulator.

All models are Python dataclasses with to_dict() and from_dict() methods
for serialization round-trips.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


def _generate_id() -> str:
    """Generate a UUID v4 string."""
    return str(uuid.uuid4())


def _now_timestamp() -> str:
    """Generate an ISO 8601 timestamp with Z suffix."""
    return datetime.utcnow().isoformat() + "Z"


@dataclass
class Token:
    """Simulated Keystone authentication token."""

    id: str
    username: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Token:
        return cls(
            id=data["id"],
            username=data["username"],
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
        )


@dataclass
class Instance:
    """Simulated Nova compute instance."""

    id: str
    name: str
    flavor: str
    image: str
    status: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "flavor": self.flavor,
            "image": self.image,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Instance:
        return cls(
            id=data["id"],
            name=data["name"],
            flavor=data["flavor"],
            image=data["image"],
            status=data["status"],
            created_at=data["created_at"],
        )


@dataclass
class Network:
    """Simulated Neutron network."""

    id: str
    name: str
    status: str
    created_at: str
    subnet_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "subnet_ids": list(self.subnet_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Network:
        return cls(
            id=data["id"],
            name=data["name"],
            status=data["status"],
            created_at=data["created_at"],
            subnet_ids=list(data.get("subnet_ids", [])),
        )


@dataclass
class Subnet:
    """Simulated Neutron subnet."""

    id: str
    name: str
    network_id: str
    cidr: str
    gateway: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "network_id": self.network_id,
            "cidr": self.cidr,
            "gateway": self.gateway,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Subnet:
        return cls(
            id=data["id"],
            name=data["name"],
            network_id=data["network_id"],
            cidr=data["cidr"],
            gateway=data["gateway"],
        )


@dataclass
class Router:
    """Simulated Neutron router."""

    id: str
    name: str
    status: str
    subnet_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "subnet_ids": list(self.subnet_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Router:
        return cls(
            id=data["id"],
            name=data["name"],
            status=data["status"],
            subnet_ids=list(data.get("subnet_ids", [])),
        )


@dataclass
class Port:
    """Simulated Neutron port."""

    id: str
    name: str
    network_id: str
    mac_address: str
    status: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "network_id": self.network_id,
            "mac_address": self.mac_address,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Port:
        return cls(
            id=data["id"],
            name=data["name"],
            network_id=data["network_id"],
            mac_address=data["mac_address"],
            status=data["status"],
        )


@dataclass
class Bond:
    """Simulated LACP bond."""

    id: str
    name: str
    port_ids: list[str] = field(default_factory=list)
    bond_mode: str = ""
    status: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "port_ids": list(self.port_ids),
            "bond_mode": self.bond_mode,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Bond:
        return cls(
            id=data["id"],
            name=data["name"],
            port_ids=list(data.get("port_ids", [])),
            bond_mode=data["bond_mode"],
            status=data["status"],
        )


@dataclass
class Volume:
    """Simulated Cinder volume."""

    id: str
    name: str
    size: int
    status: str
    created_at: str
    attached_to: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "size": self.size,
            "status": self.status,
            "created_at": self.created_at,
            "attached_to": self.attached_to,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Volume:
        return cls(
            id=data["id"],
            name=data["name"],
            size=data["size"],
            status=data["status"],
            created_at=data["created_at"],
            attached_to=data.get("attached_to"),
        )


@dataclass
class Rule:
    """A single security group rule."""

    id: str
    security_group_id: str
    protocol: str
    port_range: str
    direction: str
    remote_ip_prefix: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "security_group_id": self.security_group_id,
            "protocol": self.protocol,
            "port_range": self.port_range,
            "direction": self.direction,
            "remote_ip_prefix": self.remote_ip_prefix,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Rule:
        return cls(
            id=data["id"],
            security_group_id=data["security_group_id"],
            protocol=data["protocol"],
            port_range=data["port_range"],
            direction=data["direction"],
            remote_ip_prefix=data["remote_ip_prefix"],
        )


@dataclass
class SecurityGroup:
    """Simulated Neutron security group."""

    id: str
    name: str
    description: str
    rules: list[Rule] = field(default_factory=list)
    created_at: str = ""
    status: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "rules": [rule.to_dict() for rule in self.rules],
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SecurityGroup:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            rules=[Rule.from_dict(r) for r in data.get("rules", [])],
            created_at=data["created_at"],
            status=data["status"],
        )


@dataclass
class BaremetalNode:
    """Simulated Ironic baremetal node."""

    id: str
    name: str
    driver: str
    power_state: str
    provision_state: str
    memory_mb: int
    cpus: int
    local_gb: int
    cpu_arch: str
    driver_info: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)
    status: str = "ACTIVE"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "driver": self.driver,
            "power_state": self.power_state,
            "provision_state": self.provision_state,
            "memory_mb": self.memory_mb,
            "cpus": self.cpus,
            "local_gb": self.local_gb,
            "cpu_arch": self.cpu_arch,
            "driver_info": dict(self.driver_info),
            "properties": dict(self.properties),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BaremetalNode:
        return cls(
            id=data["id"],
            name=data["name"],
            driver=data["driver"],
            power_state=data["power_state"],
            provision_state=data["provision_state"],
            memory_mb=data["memory_mb"],
            cpus=data["cpus"],
            local_gb=data["local_gb"],
            cpu_arch=data["cpu_arch"],
            driver_info=dict(data.get("driver_info", {})),
            properties=dict(data.get("properties", {})),
            status=data.get("status", "ACTIVE"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class Snapshot:
    """Snapshot of an instance or volume."""

    id: str
    name: str
    source_id: str
    source_type: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot:
        return cls(
            id=data["id"],
            name=data["name"],
            source_id=data["source_id"],
            source_type=data["source_type"],
            created_at=data["created_at"],
        )


@dataclass
class BaremetalPort:
    """Simulated Ironic baremetal port (network interface)."""

    id: str
    node_id: str
    address: str  # MAC address
    status: str = "ACTIVE"
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "address": self.address,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BaremetalPort:
        return cls(
            id=data["id"],
            node_id=data["node_id"],
            address=data["address"],
            status=data.get("status", "ACTIVE"),
            created_at=data.get("created_at", ""),
        )
