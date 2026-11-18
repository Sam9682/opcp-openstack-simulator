"""Main entry point for the OpenStack Simulator."""

from __future__ import annotations

import configparser
import threading
from pathlib import Path

from openstack_simulator.clock import Clock
from openstack_simulator.limiter import ResourceLimiter
from openstack_simulator.managers.auth import AuthManager
from openstack_simulator.managers.baremetal import BaremetalManager
from openstack_simulator.managers.compute import ComputeManager
from openstack_simulator.managers.image import ImageManager
from openstack_simulator.managers.image_lookup import ImageLookup
from openstack_simulator.managers.network import NetworkManager
from openstack_simulator.managers.node_service import NodeService
from openstack_simulator.managers.placement import PlacementService
from openstack_simulator.managers.quota import QuotaManager
from openstack_simulator.managers.security_group import SecurityGroupManager
from openstack_simulator.managers.server_service import ServerCreationService
from openstack_simulator.managers.transitions import FailureInjector
from openstack_simulator.managers.volume import VolumeManager
from openstack_simulator.sim_config import load_sim_config
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
    "compute.max_cores": "max_cores",
    "compute.max_ram": "max_ram",
    "compute.max_key_pairs": "max_key_pairs",
    "compute.max_server_groups": "max_server_groups",
    "compute.max_server_group_members": "max_server_group_members",
}

# Optional Quota keys: absent means no limit (Req 18.8).
_OPTIONAL_QUOTAS: dict[str, str] = {
    "max_cores": "cores",
    "max_ram": "ram",
    "max_key_pairs": "key_pairs",
    "max_server_groups": "server_groups",
    "max_server_group_members": "server_group_members",
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

        # Sim_Config (constructor config dict wins over the file); a
        # ConfigError propagates and fails startup.
        self.sim_config = load_sim_config(overrides=config)

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

        limits = self.limiter.limits
        for cfg_key, quota in _OPTIONAL_QUOTAS.items():
            if cfg_key in self.config:
                limits[quota] = int(self.config[cfg_key])

        self.clock = Clock()
        self.lock = threading.RLock()
        self.failures = FailureInjector()
        self.placement = PlacementService(lock=self.lock)
        self.images = ImageLookup(self.store)
        self.node_service = NodeService(
            self.store,
            self.sim_config,
            self.placement,
            failures=self.failures,
            lock=self.lock,
            images=self.images,
        )
        self.quota_manager = QuotaManager(
            self.store, self.limiter, self.sim_config
        )
        self.server_service = ServerCreationService(
            self.store,
            self.sim_config,
            self.placement,
            self.node_service,
            self.quota_manager,
            self.images,
            lock=self.lock,
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
        self.baremetal_manager = BaremetalManager(
            store=self.store,
            limiter=self.limiter,
            node_service=self.node_service,
            clock=self.clock,
        )
        self.image_manager = ImageManager(store=self.store)
        self.image_manager.seed_predefined()
        self.resync_traits()

    def reset(self) -> None:
        """Clear the store in place and seed the predefined images again."""
        with self.lock:
            self.store.clear()
            self.image_manager.seed_predefined()

    def resync_traits(self) -> None:
        """Create missing placement providers and make their traits match
        the nodes (the node is the source of truth)."""
        with self.lock:
            nodes = self.store.list_active("baremetal_nodes")
            for node in nodes:
                self.placement.ensure_provider(node)
            self.placement.resync_traits(nodes)
