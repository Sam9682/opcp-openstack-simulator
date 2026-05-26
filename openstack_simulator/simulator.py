"""Main entry point for the OpenStack Simulator."""

from __future__ import annotations

from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.auth import AuthManager
from openstack_simulator.managers.compute import ComputeManager
from openstack_simulator.managers.network import NetworkManager
from openstack_simulator.managers.security_group import SecurityGroupManager
from openstack_simulator.managers.volume import VolumeManager
from openstack_simulator.store import ResourceStore

DEFAULT_CONFIG: dict[str, object] = {
    "default_flavor": "m1.small",
    "default_image": "ubuntu-22.04",
    "session_timeout": 120,
    "max_instances": 3,
    "max_networks": 2,
    "max_volumes": 3,
    "max_security_groups": 5,
}


class Simulator:
    """Main entry point. Initializes all managers with shared state."""

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the simulator with optional configuration overrides.

        Default config:
            default_flavor: "m1.small"
            default_image: "ubuntu-22.04"
            session_timeout: 120  (minutes)
            max_instances: 3
            max_networks: 2
            max_volumes: 3
            max_security_groups: 5
        """
        self.config: dict = {**DEFAULT_CONFIG, **(config or {})}

        self.store = ResourceStore()

        self.limiter = ResourceLimiter(
            limits={
                "instances": int(self.config["max_instances"]),
                "networks": int(self.config["max_networks"]),
                "volumes": int(self.config["max_volumes"]),
                "security_groups": int(self.config["max_security_groups"]),
            }
        )

        self.auth_manager = AuthManager(
            store=self.store,
            session_timeout=int(self.config["session_timeout"]),
        )
        self.compute_manager = ComputeManager(store=self.store, limiter=self.limiter)
        self.network_manager = NetworkManager(store=self.store, limiter=self.limiter)
        self.volume_manager = VolumeManager(store=self.store, limiter=self.limiter)
        self.security_group_manager = SecurityGroupManager(
            store=self.store, limiter=self.limiter
        )
