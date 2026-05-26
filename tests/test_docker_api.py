"""End-to-end test of the Docker-hosted OpenStack Simulator API."""

import json
import urllib.request
import sys

BASE = "http://localhost:5000"


def main():
    # 1. Get token via application_credential auth
    auth_body = json.dumps({
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {
                    "id": "simulator-app-credential",
                    "secret": "simulator-secret",
                },
            }
        }
    }).encode()

    req = urllib.request.Request(
        f"{BASE}/identity/v3/auth/tokens",
        data=auth_body,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 201, f"Expected 201, got {resp.status}"
    token = resp.headers["X-Subject-Token"]
    body = json.loads(resp.read())
    assert "token" in body
    assert "catalog" in body["token"]
    print(f"[OK] Token issued: {token[:20]}...")
    print(f"     Service catalog: {len(body['token']['catalog'])} services")

    # 2. List servers (should be empty)
    req = urllib.request.Request(
        f"{BASE}/compute/v2.1/servers",
        headers={"X-Auth-Token": token},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data == {"servers": []}
    print("[OK] Compute: server list empty")

    # 3. Create a server
    server_body = json.dumps({
        "server": {"name": "docker-test-vm", "flavorRef": "m1.small", "imageRef": "ubuntu-22.04"}
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/compute/v2.1/servers",
        data=server_body,
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 202
    data = json.loads(resp.read())
    assert data["server"]["name"] == "docker-test-vm"
    assert data["server"]["status"] == "ACTIVE"
    print("[OK] Compute: server created")

    # 4. List networks (should be empty)
    req = urllib.request.Request(
        f"{BASE}/network/v2.0/networks",
        headers={"X-Auth-Token": token},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data == {"networks": []}
    print("[OK] Network: network list empty")

    # 5. Create a network
    net_body = json.dumps({"network": {"name": "docker-test-net"}}).encode()
    req = urllib.request.Request(
        f"{BASE}/network/v2.0/networks",
        data=net_body,
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 201
    data = json.loads(resp.read())
    assert data["network"]["name"] == "docker-test-net"
    print("[OK] Network: network created")

    # 6. List volumes (should be empty)
    req = urllib.request.Request(
        f"{BASE}/volume/v3/fake-project-id-00000000001/volumes",
        headers={"X-Auth-Token": token},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data == {"volumes": []}
    print("[OK] Volume: volume list empty")

    # 7. Create a volume
    vol_body = json.dumps({"volume": {"name": "docker-test-vol", "size": 10}}).encode()
    req = urllib.request.Request(
        f"{BASE}/volume/v3/fake-project-id-00000000001/volumes",
        data=vol_body,
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    assert resp.status == 202
    data = json.loads(resp.read())
    assert data["volume"]["name"] == "docker-test-vol"
    assert data["volume"]["size"] == 10
    print("[OK] Volume: volume created")

    print("\n=== All Docker API tests passed! ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
