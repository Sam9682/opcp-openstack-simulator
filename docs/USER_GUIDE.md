# User Guide

## Getting Started

This guide walks you through using the OpenStack Simulator with the standard OpenStack CLI. The simulator behaves like a real OpenStack environment — same commands, same responses, same error messages.

## Prerequisites

1. The simulator is running (see [Deployment Guide](DEPLOYMENT_GUIDE.md))
2. The OpenStack CLI is installed:

```bash
pip install python-openstackclient
```

3. Environment is configured:

```bash
export OS_AUTH_URL=http://localhost:5000/identity/v3
export OS_APPLICATION_CREDENTIAL_ID=simulator-app-credential
export OS_APPLICATION_CREDENTIAL_SECRET=simulator-secret
export OS_REGION_NAME=RegionOne
export OS_INTERFACE=public
export OS_IDENTITY_API_VERSION=3
export OS_AUTH_TYPE=v3applicationcredential
```

## Authentication

The simulator accepts any non-empty credential pair. No real user database exists — if the ID and secret are non-empty strings, authentication succeeds.

```bash
# Verify authentication works
openstack token issue
```

Expected output:
```
+------------+----------------------------------+
| Field      | Value                            |
+------------+----------------------------------+
| expires    | 2026-05-28T10:00:00.000000Z      |
| id         | a1b2c3d4-e5f6-...                |
| project_id | fake-project-id-00000000001      |
| user_id    | ...                              |
+------------+----------------------------------+
```

---

## Compute (Nova) — Managing Servers

### Create a Server

```bash
openstack server create --flavor m1.small --image ubuntu-22.04 my-server
```

Available flavors: `m1.tiny`, `m1.small`, `m1.medium`, `m1.large`, `m1.xlarge`
Available images: `ubuntu-22.04`, `ubuntu-20.04`, `centos-8`, `debian-11`

### List Servers

```bash
openstack server list
```

### Show Server Details

```bash
openstack server show my-server
```

### Delete a Server

```bash
openstack server delete my-server
```

### Resource Limits

The simulator enforces a default limit of **3 instances**. Creating a 4th server returns an error:

```
HttpException: 413: instances limit (3) reached
```

Delete an existing server to free a slot.

---

## Networking (Neutron) — Managing Networks

### Create a Network

```bash
openstack network create my-network
```

### Create a Subnet

```bash
openstack subnet create --network my-network --subnet-range 10.0.0.0/24 --gateway 10.0.0.1 my-subnet
```

### Create a Router

```bash
openstack router create my-router
```

### Add Router Interface

```bash
openstack router add subnet my-router my-subnet
```

### Create a Port

```bash
openstack port create --network my-network my-port
```

### List Resources

```bash
openstack network list
openstack subnet list
openstack router list
openstack port list
```

### Delete a Network

```bash
openstack network delete my-network
```

### Resource Limits

Default limit: **2 networks**. Delete existing networks to create new ones.

---

## Block Storage (Cinder) — Managing Volumes

### Create a Volume

```bash
openstack volume create --size 10 my-volume
```

### List Volumes

```bash
openstack volume list
```

### Show Volume Details

```bash
openstack volume show my-volume
```

### Delete a Volume

```bash
openstack volume delete my-volume
```

### Resource Limits

Default limit: **3 volumes**. Volumes that are attached ("in-use") cannot be deleted — detach first.

---

## Security Groups — Managing Firewall Rules

### Create a Security Group

```bash
openstack security group create --description "Allow web traffic" web-sg
```

### Add Rules

```bash
# Allow HTTP
openstack security group rule create --protocol tcp --dst-port 80 web-sg

# Allow HTTPS
openstack security group rule create --protocol tcp --dst-port 443 web-sg

# Allow SSH
openstack security group rule create --protocol tcp --dst-port 22 web-sg

# Allow ICMP (ping)
openstack security group rule create --protocol icmp web-sg
```

### List Security Groups

```bash
openstack security group list
```

### Show Rules

```bash
openstack security group show web-sg
```

### Delete a Security Group

```bash
openstack security group delete web-sg
```

### Resource Limits

Default limit: **5 security groups**.

---

## Error Reference

The simulator returns the same error types as real OpenStack:

| Error | Meaning | What to Do |
|-------|---------|------------|
| 401 Unauthorized | Invalid or expired token | Re-authenticate (check env vars) |
| 404 Not Found | Resource doesn't exist | Check the resource name/ID |
| 409 Conflict | Duplicate name or invalid state | Use a different name, or fix the state |
| 413 Over Limit | Quota exceeded | Delete existing resources first |

---

## Python SDK Usage

You can also use the simulator directly as a Python library (without HTTP):

```python
from openstack_simulator import Simulator

sim = Simulator()

# Authenticate
token = sim.auth_manager.authenticate("admin", "secret")

# Create resources
instance = sim.compute_manager.create("web-server", "m1.small", "ubuntu-22.04")
network = sim.network_manager.create("app-network")
volume = sim.volume_manager.create("data-disk", 100)
sg = sim.security_group_manager.create("web-sg", "Allow HTTP")

# Manage resources
sim.volume_manager.attach("data-disk", "web-server")
sim.security_group_manager.add_rule("web-sg", "tcp", "80:80", "ingress", "0.0.0.0/0")
sim.compute_manager.resize("web-server", "m1.large")

# Clean up
sim.compute_manager.delete("web-server")
sim.network_manager.delete("app-network")
sim.volume_manager.delete("data-disk")
sim.security_group_manager.delete("web-sg")
```

---

## Tips

- **State is ephemeral** — restarting the simulator clears all resources. This is by design for training.
- **Any credentials work** — the simulator doesn't validate users against a database. Any non-empty ID/secret pair succeeds.
- **Quotas are enforced** — just like real OpenStack. Delete resources to free quota.
- **Names must be unique** — you can't create two resources of the same type with the same name.
- **Soft-delete** — deleted resources are hidden but still exist internally. They don't count toward quotas.
