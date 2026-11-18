"""CallerContext, clock override and SimError handler (server-creation-rules task 8.1)."""

import json

import pytest
from flask import g

from openstack_simulator.api.app import create_app
from openstack_simulator.api.helpers import (
    CallerContext,
    DEFAULT_MICROVERSION,
    parse_microversion,
    require_token,
)
from openstack_simulator.exceptions import (
    BadRequest,
    NodeLocked,
    ServerNotFound,
)


@pytest.fixture
def app():
    app = create_app({"time_scale": 0})
    seen = {}

    @app.route("/compute/v2.1/_probe")
    @require_token
    def probe_compute():
        seen["ctx"] = g.caller_context
        return {"ok": True}

    @app.route("/compute/v2.1/_notfound")
    def notfound():
        raise ServerNotFound("Instance x could not be found.")

    @app.route("/baremetal/v1/_locked")
    def locked():
        raise NodeLocked("Node is locked")

    app.config["SEEN"] = seen
    return app


@pytest.fixture
def client_headers(app):
    token = app.config["SIMULATOR"].auth_manager.authenticate("u", "p")
    return app.test_client(), {"X-Auth-Token": token.id}


def test_default_context(app, client_headers):
    c, h = client_headers
    assert c.get("/compute/v2.1/_probe", headers=h).status_code == 200
    ctx = app.config["SEEN"]["ctx"]
    assert isinstance(ctx, CallerContext)
    assert ctx.is_admin is True
    assert ctx.microversion == DEFAULT_MICROVERSION
    assert ctx.project_id == app.config["PROJECT_ID"]


def test_query_now_wins_over_header(app, client_headers):
    c, h = client_headers
    h = {**h, "X-Sim-Now": "500"}
    c.get("/compute/v2.1/_probe?now=100", headers=h)
    assert app.config["SEEN"]["ctx"].now == 100.0
    c.get("/compute/v2.1/_probe", headers=h)
    assert app.config["SEEN"]["ctx"].now == 500.0


def test_invalid_now_is_400(client_headers):
    c, h = client_headers
    r = c.get("/compute/v2.1/_probe?now=garbage", headers=h)
    assert r.status_code == 400
    assert "badRequest" in r.get_json()
    r = c.get("/compute/v2.1/_probe", headers={**h, "X-Sim-Now": "nan"})
    assert r.status_code == 400


def test_override_does_not_change_offset(app, client_headers):
    c, h = client_headers
    clock = app.config["SIMULATOR"].clock
    c.get("/compute/v2.1/_probe?now=12345", headers=h)
    assert clock.now() != 12345.0


def test_microversion_parsing():
    assert parse_microversion({"OpenStack-API-Version": "compute 2.78"}) == (2, 78)
    assert parse_microversion({"X-OpenStack-Nova-API-Version": "2.60"}) == (2, 60)
    assert parse_microversion({"OpenStack-API-Version": "baremetal 1.80"}) == DEFAULT_MICROVERSION
    assert parse_microversion({}) == DEFAULT_MICROVERSION
    with pytest.raises(BadRequest):
        parse_microversion({"X-OpenStack-Nova-API-Version": "abc"})


def test_compute_envelope(app):
    r = app.test_client().get("/compute/v2.1/_notfound")
    assert r.status_code == 404
    assert r.get_json()["itemNotFound"]["code"] == 404


def test_ironic_envelope(app):
    r = app.test_client().get("/baremetal/v1/_locked")
    assert r.status_code == 409
    inner = json.loads(r.get_json()["error_message"])
    assert inner["faultstring"] == "Node is locked"
    assert inner["faultcode"] == "Client"
