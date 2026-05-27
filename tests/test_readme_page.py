"""Test that the root endpoint renders README.md as HTML."""

from openstack_simulator.api.app import create_app


def test_root_html():
    app = create_app()
    client = app.test_client()
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    data = resp.data.decode()
    assert "<!DOCTYPE html>" in data
    assert "OpenStack Simulator" in data
    assert "<table>" in data
    print(f"HTML page rendered: {len(data)} chars")


def test_root_json():
    app = create_app()
    client = app.test_client()
    resp = client.get("/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "versions" in data


if __name__ == "__main__":
    test_root_html()
    test_root_json()
    print("All tests passed!")
