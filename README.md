# OpenStack Simulator

A pure-Python, in-memory OpenStack simulator designed for the `opcp-openstack-first-steps` training framework. It provides drop-in replacements for Keystone (auth), Nova (compute), Neutron (networking), and Cinder (block storage) manager interfaces — no live OpenStack environment required.

## Features

- Simulated authentication with token issuance and expiry
- Compute instance lifecycle: create, get, resize, snapshot, delete
- Networking: networks, subnets, routers, ports, and LACP bonds
- Block storage: volumes with attach/detach and snapshots
- Security groups with ingress/egress rule management
- Realistic UUIDs (v4) and ISO 8601 timestamps
- Configurable resource quotas (mimics real OpenStack limits)
- Custom exception hierarchy matching OpenStack error semantics

## Requirements

- Python 3.9+
- nginx (optional, for production deployment)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd opcp-openstack-simulator

# Install in development mode (includes Flask and gunicorn)
pip install -e .

# Install with test dependencies
pip install -e ".[dev]"
```

## Quick Start

```python
from openstack_simulator import Simulator

# Create a simulator with default configuration
sim = Simulator()

# Authenticate
token = sim.auth_manager.authenticate("admin", "secret")
print(f"Token: {token.id}")

# Create a compute instance
instance = sim.compute_manager.create("web-server", "m1.small", "ubuntu-22.04")
print(f"Instance: {instance.name} ({instance.status})")

# Create a network and subnet
network = sim.network_manager.create("app-network")
subnet = sim.network_manager.create_subnet(
    "app-network", "app-subnet", "10.0.0.0/24", "10.0.0.1"
)

# Create a volume and attach it
volume = sim.volume_manager.create("data-disk", 100)
sim.volume_manager.attach("data-disk", "web-server")
print(f"Volume: {volume.name} → {volume.status}")

# Create a security group with a rule
sg = sim.security_group_manager.create("web-sg", "Allow HTTP")
sim.security_group_manager.add_rule("web-sg", "tcp", "80:80", "ingress", "0.0.0.0/0")
```

## Configuration

The simulator accepts an optional config dict to override defaults:

```python
sim = Simulator(config={
    "default_flavor": "m1.small",
    "default_image": "ubuntu-22.04",
    "session_timeout": 120,       # Token validity in minutes
    "max_instances": 3,           # Max compute instances
    "max_networks": 2,            # Max networks
    "max_volumes": 3,             # Max volumes
    "max_security_groups": 5,     # Max security groups
})
```

Only include the keys you want to override — unspecified keys keep their defaults.

## API Reference

### Simulator

The `Simulator` class is the main entry point. It exposes five manager attributes:

| Attribute | Manager | Purpose |
|-----------|---------|---------|
| `sim.auth_manager` | AuthManager | Authentication and token management |
| `sim.compute_manager` | ComputeManager | Instance lifecycle |
| `sim.network_manager` | NetworkManager | Networks, subnets, routers, ports, bonds |
| `sim.volume_manager` | VolumeManager | Volume lifecycle and attachments |
| `sim.security_group_manager` | SecurityGroupManager | Security groups and rules |

### AuthManager

```python
# Authenticate (returns a Token)
token = sim.auth_manager.authenticate(username, password)

# Validate a token (returns True or raises)
sim.auth_manager.validate_token(token.id)
```

### ComputeManager

```python
sim.compute_manager.create(name, flavor, image)   # → Instance
sim.compute_manager.get(name)                      # → Instance | None
sim.compute_manager.resize(name, new_flavor)       # → Instance
sim.compute_manager.snapshot(name, snapshot_name)  # → Snapshot
sim.compute_manager.delete(name)                   # → None
sim.compute_manager.list()                         # → list[Instance]
```

### NetworkManager

```python
sim.network_manager.create(name)                                        # → Network
sim.network_manager.get(name)                                           # → Network | None
sim.network_manager.create_subnet(network_name, name, cidr, gateway)   # → Subnet
sim.network_manager.create_router(name)                                 # → Router
sim.network_manager.add_router_interface(router_name, subnet_id)        # → None
sim.network_manager.create_port(network_name, name)                     # → Port
sim.network_manager.create_bond(name, port_names, bond_mode)            # → Bond
sim.network_manager.delete(name)                                        # → None
sim.network_manager.list()                                              # → list[Network]
```

### VolumeManager

```python
sim.volume_manager.create(name, size)                # → Volume
sim.volume_manager.get(name)                         # → Volume | None
sim.volume_manager.attach(volume_name, instance_name)  # → Volume
sim.volume_manager.snapshot(name, snapshot_name)     # → Snapshot
sim.volume_manager.delete(name)                      # → None
sim.volume_manager.list()                            # → list[Volume]
```

### SecurityGroupManager

```python
sim.security_group_manager.create(name, description)                          # → SecurityGroup
sim.security_group_manager.get(name)                                          # → SecurityGroup | None
sim.security_group_manager.add_rule(sg_name, protocol, port_range, direction, remote_ip_prefix)  # → Rule
sim.security_group_manager.delete_rule(rule_id)                               # → None
sim.security_group_manager.delete(name)                                       # → None
sim.security_group_manager.list()                                             # → list[SecurityGroup]
```

## Error Handling

All errors inherit from `SimulatorError`, so you can catch them broadly or specifically:

```python
from openstack_simulator import (
    SimulatorError,
    AuthenticationError,
    TokenExpiredError,
    ResourceLimitExceededError,
    DuplicateResourceError,
    ResourceNotFoundError,
    InvalidStateError,
)

try:
    sim.compute_manager.create("server-4", "m1.small", "ubuntu-22.04")
except ResourceLimitExceededError as e:
    print(f"Quota exceeded: {e.message}")
except SimulatorError as e:
    print(f"Simulator error: {e.message}")
```

| Exception | When it's raised |
|-----------|-----------------|
| `AuthenticationError` | Empty username or password |
| `TokenExpiredError` | Validating an expired token |
| `ResourceLimitExceededError` | Creating a resource beyond the quota |
| `DuplicateResourceError` | Creating a resource with an existing name |
| `ResourceNotFoundError` | Operating on a resource that doesn't exist |
| `InvalidStateError` | Invalid operation for current state (e.g., deleting an attached volume) |

## Resource Limits

The simulator enforces quotas just like a real OpenStack environment:

| Resource | Default Limit |
|----------|--------------|
| Instances | 3 |
| Networks | 2 |
| Volumes | 3 |
| Security Groups | 5 |

Deleting a resource frees its quota slot, allowing new resources to be created.

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=openstack_simulator --cov-report=term-missing
```

## Web API — Using with the OpenStack CLI

The simulator exposes a full OpenStack-compatible REST API that works with the standard `python-openstackclient` CLI.

### Starting the API Server

```bash
# Development mode (Flask dev server, port 8000)
./deploy/start.sh --dev

# Production mode (gunicorn, port 8000 — use nginx to expose on port 5000)
./deploy/start.sh
```

### Configuring the OpenStack CLI

1. Install the OpenStack CLI:

```bash
pip install python-openstackclient
```

2. Copy the provided `clouds.yaml` to your OpenStack config directory:

```bash
mkdir -p ~/.config/openstack
cp deploy/clouds.yaml ~/.config/openstack/clouds.yaml
```

3. Use the simulator:

```bash
# Set the cloud (or pass --os-cloud simulator to each command)
export OS_CLOUD=simulator

# Authenticate and list servers
openstack server list

# Create a server
openstack server create --flavor m1.small --image ubuntu-22.04 my-server

# Create a network
openstack network create my-network

# Create a volume
openstack volume create --size 10 my-volume

# Create a security group
openstack security group create my-sg

# Add a rule
openstack security group rule create --protocol tcp --dst-port 80 my-sg
```

### Application Credentials

The simulator accepts any non-empty application credential ID and secret. The default `clouds.yaml` uses:

|           Field                 |                Value                |
|---------------------------------|-------------------------------------|
| `auth_url`                      | `http://localhost:5000/identity/v3` |
| `application_credential_id`     | `simulator-app-credential`          |
| `application_credential_secret` | `simulator-secret`                  |
| `auth_type`                     | `v3applicationcredential`           |

You can also use password-based authentication:

```yaml
clouds:
  simulator:
    auth:
      auth_url: http://localhost:5000/identity/v3
      username: admin
      password: admin
      project_name: simulator-project
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
    identity_api_version: 3
```

### Nginx Setup (Production)

The nginx config proxies port 5000 (standard Keystone port) to the gunicorn backend on port 8000.

```bash
# Copy the nginx config
sudo cp deploy/nginx/openstack-simulator.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/openstack-simulator.conf /etc/nginx/sites-enabled/

# Test and reload nginx
sudo nginx -t
sudo systemctl reload nginx
```

Without nginx, you can point the CLI directly at port 8000:

```yaml
# In clouds.yaml, change auth_url to:
auth_url: http://localhost:8000/identity/v3
```

### API Endpoints

|      Service        |         Base Path          |                    Description                     |
|---------------------|----------------------------|----------------------------------------------------|
| Identity (Keystone) | `/identity/v3/`            | Authentication, token management                   |
| Compute (Nova)      | `/compute/v2.1/`           | Servers, flavors, images                           |
| Network (Neutron)   | `/network/v2.0/`           | Networks, subnets, routers, ports, security groups |
| Volume (Cinder)     | `/volume/v3/{project_id}/` | Volumes, snapshots                                 |

## Project Structure

```
openstack_simulator/
├── __init__.py              # Public API exports
├── simulator.py             # Simulator facade
├── models.py                # Dataclass models (Token, Instance, Network, etc.)
├── store.py                 # ResourceStore — in-memory storage
├── limiter.py               # ResourceLimiter — quota enforcement
├── exceptions.py            # Custom exception hierarchy
└── managers/
    ├── __init__.py
    ├── auth.py              # AuthManager
    ├── compute.py           # ComputeManager
    ├── network.py           # NetworkManager
    ├── volume.py            # VolumeManager
    └── security_group.py    # SecurityGroupManager
tests/
├── conftest.py              # Shared fixtures and Hypothesis strategies
├── test_infrastructure_smoke.py
├── test_managers_checkpoint.py
└── test_all_managers_checkpoint.py
```

## License

MIT
