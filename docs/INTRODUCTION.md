# Introduction

## What is the OPCP OpenStack Simulator?

The OPCP OpenStack Simulator is a lightweight, pure-Python, in-memory simulation of core OpenStack services. It is designed as a drop-in replacement for real OpenStack API calls, enabling users to run the `opcp-openstack-first-steps` training project without access to a live OpenStack platform.

The simulator implements the same manager interfaces and REST API endpoints that the training exercises call, tracks resource state in memory, enforces resource limits, and produces realistic responses (UUIDs, timestamps, status transitions).

## Why Use a Simulator?

Running a full OpenStack environment (even DevStack) requires significant resources — multiple GBs of RAM, many CPU cores, and complex networking. For training purposes, this is overkill. The simulator provides:

- **Zero infrastructure cost** — runs on any machine with Python 3.9+
- **Instant startup** — no waiting for services to boot
- **Deterministic behavior** — no flaky network calls or race conditions
- **Realistic responses** — UUIDs, timestamps, status codes, and error messages match real OpenStack
- **Quota enforcement** — mimics real OpenStack resource limits
- **Full CLI compatibility** — works with the standard `python-openstackclient`

## Simulated Services

| OpenStack Service | Simulator Component | What It Does |
|-------------------|---------------------|--------------|
| Keystone (Identity) | AuthManager | Token issuance, validation, expiry |
| Nova (Compute) | ComputeManager | Instance create, get, resize, snapshot, delete |
| Neutron (Network) | NetworkManager | Networks, subnets, routers, ports, LACP bonds |
| Cinder (Block Storage) | VolumeManager | Volumes, attach/detach, snapshots |
| Neutron (Security) | SecurityGroupManager | Security groups and ingress/egress rules |

## How It Works

The simulator is a single Python package (`openstack_simulator`) with three layers:

1. **Facade Layer** — The `Simulator` class is the single entry point. It initializes all managers and holds configuration.
2. **Manager Layer** — Five managers implement domain-specific operations (auth, compute, network, volume, security groups). Each manager validates inputs, enforces limits, and mutates state.
3. **Infrastructure Layer** — A shared `ResourceStore` (in-memory dictionaries) and `ResourceLimiter` (quota enforcement) provide the foundation.

The REST API layer (Flask + gunicorn) wraps the managers with HTTP endpoints that match the real OpenStack API format, so the standard CLI works unchanged.

## Target Audience

- **Training lab students** completing the `opcp-openstack-first-steps` exercises
- **Instructors** who need a portable OpenStack environment for demos
- **Developers** building tools that interact with OpenStack APIs and need a fast test backend

## Next Steps

- [Architecture Guide](ARCHITECTURE_GUIDE.md) — understand the internal design
- [Deployment Guide](DEPLOYMENT_GUIDE.md) — get the simulator running
- [User Guide](USER_GUIDE.md) — start using the simulator with the OpenStack CLI
