# pytest conftest for openstack_simulator tests
# Shared fixtures and Hypothesis strategies for property-based testing.
# Requirements: 1.1, 1.4

import pytest
from hypothesis import strategies as st

from openstack_simulator import Simulator
from openstack_simulator.store import ResourceStore
from openstack_simulator.limiter import ResourceLimiter


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simulator():
    """Return a fresh Simulator instance with default config."""
    return Simulator()


@pytest.fixture
def auth_manager(simulator):
    """Return the AuthManager from a fresh Simulator."""
    return simulator.auth_manager


@pytest.fixture
def compute_manager(simulator):
    """Return the ComputeManager from a fresh Simulator."""
    return simulator.compute_manager


@pytest.fixture
def network_manager(simulator):
    """Return the NetworkManager from a fresh Simulator."""
    return simulator.network_manager


@pytest.fixture
def volume_manager(simulator):
    """Return the VolumeManager from a fresh Simulator."""
    return simulator.volume_manager


@pytest.fixture
def security_group_manager(simulator):
    """Return the SecurityGroupManager from a fresh Simulator."""
    return simulator.security_group_manager


@pytest.fixture
def store():
    """Return a fresh ResourceStore for infrastructure tests."""
    return ResourceStore()


@pytest.fixture
def limiter():
    """Return a ResourceLimiter with default limits."""
    return ResourceLimiter(
        limits={"instances": 3, "networks": 2, "volumes": 3, "security_groups": 5}
    )


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Strategy for valid resource names (non-empty, printable, no whitespace-only)
resource_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"), whitelist_characters="-_"
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

# Strategy for flavors
flavors = st.sampled_from(["m1.tiny", "m1.small", "m1.medium", "m1.large", "m1.xlarge"])

# Strategy for images
images = st.sampled_from(
    ["ubuntu-22.04", "ubuntu-20.04", "centos-8", "debian-11", "fedora-37"]
)

# Strategy for volume sizes (1-1000 GB)
volume_sizes = st.integers(min_value=1, max_value=1000)

# Strategy for CIDR blocks
cidrs = st.sampled_from(
    ["10.0.0.0/24", "192.168.1.0/24", "172.16.0.0/16", "10.0.1.0/24", "192.168.0.0/24"]
)

# Strategy for gateway IPs
gateways = st.sampled_from(
    ["10.0.0.1", "192.168.1.1", "172.16.0.1", "10.0.1.1", "192.168.0.1"]
)

# Strategy for protocols
protocols = st.sampled_from(["tcp", "udp", "icmp"])

# Strategy for port ranges
port_ranges = st.sampled_from(
    ["22:22", "80:80", "443:443", "8080:8080", "3306:3306", "5432:5432"]
)

# Strategy for directions
directions = st.sampled_from(["ingress", "egress"])

# Strategy for remote IP prefixes
ip_prefixes = st.sampled_from(
    ["0.0.0.0/0", "10.0.0.0/8", "192.168.0.0/16", "172.16.0.0/12"]
)

# Strategy for bond modes
bond_modes = st.sampled_from(
    ["802.3ad", "balance-rr", "active-backup", "balance-xor"]
)

# Strategy for descriptions
descriptions = st.text(min_size=0, max_size=200)
