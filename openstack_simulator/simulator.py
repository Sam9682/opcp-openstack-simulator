"""Main entry point for the OpenStack Simulator."""

from __future__ import annotations

import configparser
from pathlib import Path

from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.auth import AuthManager
from openstack_simulator.managers.baremetal import BaremetalManager
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
    "max_baremetal_nodes": 10,
    "max_baremetal_ports": 20,
}

# Mapping from limits.ini keys to internal config keys
_LIMITS_INI_MAP: dict[str, str] = {
    "compute.max_instances": "max_instances",
    "network.max_networks": "max_networks",
    "network.max_security_groups": "max_security_groups",
    "volume.max_volumes": "max_volumes",
    "baremetal.max_baremetal_nodes": "max_baremetal_nodes",
    "baremetal.max_baremetal_ports": "max_baremetal_ports",
}


def _load_limits_from_ini(ini_path: Path) -> dict[str, int]:
    """Load resource limits from a limits.ini file.

    Returns a dict mapping internal config keys to their integer values.
    Only keys present in _LIMITS_INI_MAP are returned.
    """
    limits: dict[str, int] = {}
    if not ini_path.exists():
        return limits

    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding="utf-8")

    for section in parser.sections():
        for key, value in parser.items(section):
            lookup = f"{section}.{key}"
            config_key = _LIMITS_INI_MAP.get(lookup)
            if config_key is not None:
                try:
                    limits[config_key] = int(value)
                except ValueError:
                    pass  # Skip non-integer values

    return limits


class Simulator:
    """Main entry point. Initializes all managers with shared state."""

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the simulator with optional configuration overrides.

        Limits are loaded in this priority order (highest wins):
            1. Programmatic config dict passed to this constructor
            2. conf/limits.ini file (looked up relative to project root or /app)
            3. DEFAULT_CONFIG hardcoded values
        """
        # Start with defaults
        self.config: dict = {**DEFAULT_CONFIG}

        # Layer in limits from conf/limits.ini
        ini_path = Path(__file__).resolve().parent.parent / "conf" / "limits.ini"
        if not ini_path.exists():
            # Fallback for Docker container layout
            ini_path = Path("/app/conf/limits.ini")
        ini_limits = _load_limits_from_ini(ini_path)
        self.config.update(ini_limits)

        # Layer in programmatic overrides
        if config:
            self.config.update(config)

        self.store = ResourceStore()

        self.limiter = ResourceLimiter(
            limits={
                "instances": int(self.config["max_instances"]),
                "networks": int(self.config["max_networks"]),
                "volumes": int(self.config["max_volumes"]),
                "security_groups": int(self.config["max_security_groups"]),
                "baremetal_nodes": int(self.config["max_baremetal_nodes"]),
                "baremetal_ports": int(self.config["max_baremetal_ports"]),
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
        self.baremetal_manager = BaremetalManager(store=self.store, limiter=self.limiter)
