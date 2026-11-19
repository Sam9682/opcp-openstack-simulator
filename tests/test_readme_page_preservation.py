"""Preservation tests for README content and the root page.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
"""

import html as _html
import os
import re
from pathlib import Path

from hypothesis import given, settings, strategies as st

from openstack_simulator.api.app import create_app

README = Path(__file__).resolve().parent.parent / "README.md"

AUTH_ROW = "| `auth_url`                      | `http://localhost:5000/identity/v3` |"
EXPORT_LINE = "export OS_AUTH_URL=http://localhost:5000/identity/v3"

_app = create_app()

hosts = st.from_regex(r"[a-z][a-z0-9]{0,10}(\.[a-z][a-z0-9]{0,8}){0,2}", fullmatch=True)
ports = st.integers(min_value=1, max_value=65535).map(str)
html_accepts = st.sampled_from(
    ["text/html", "text/html,application/xhtml+xml", "application/json, text/html;q=0.9", "*/*, text/html"]
)
non_html_accepts = st.sampled_from(
    ["", "application/json", "*/*", "text/plain", "application/xml", "image/png"]
)


def _text(body):
    """Visible text: syntax highlighting splits code lines into spans."""
    return _html.unescape(re.sub(r"<[^>]+>", "", body))


def _get(accept, host="localhost", http_port=None):
    old = os.environ.pop("HTTP_PORT", None)
    if http_port is not None:
        os.environ["HTTP_PORT"] = http_port
    try:
        headers = {"Host": host}
        if accept:
            headers["Accept"] = accept
        return _app.test_client().get("/", headers=headers)
    finally:
        os.environ.pop("HTTP_PORT", None)
        if old is not None:
            os.environ["HTTP_PORT"] = old


def test_readme_contains_verbatim_lines():
    text = README.read_text(encoding="utf-8")
    assert AUTH_ROW in text.split("\n")
    assert EXPORT_LINE in text


@settings(max_examples=30, deadline=None)
@given(accept=html_accepts, host=hosts, port=ports)
def test_html_substitutes_host_and_http_port(accept, host, port):
    resp = _get(accept, host, port)
    assert resp.status_code == 200
    body = resp.data.decode()
    url = f"http://{host}:{port}/identity/v3"
    assert f"<code>{url}</code>" in body
    assert f"export OS_AUTH_URL={url}" in _text(body)
    assert "export OS_AUTH_URL=http://localhost:5000" not in _text(body)


@settings(max_examples=20, deadline=None)
@given(accept=html_accepts, host=hosts)
def test_html_without_http_port_uses_request_host(accept, host):
    body = _get(accept, host).data.decode()
    assert f"export OS_AUTH_URL=http://{host}/identity/v3" in _text(body)
    assert f"<code>http://{host}/identity/v3</code>" in body


@settings(max_examples=30, deadline=None)
@given(accept=non_html_accepts, host=hosts, port=st.one_of(st.none(), ports))
def test_non_html_returns_version_json(accept, host, port):
    resp = _get(accept, host, port)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["versions"]["values"][0]["id"] == "v3.0"
    assert data["versions"]["values"][0]["status"] == "stable"


@settings(max_examples=10, deadline=None)
@given(host=hosts, port=ports)
def test_page_structure_preserved(host, port):
    body = _get("text/html", host, port).data.decode()
    assert "<title>OpenStack Simulator</title>" in body
    assert "In-memory training environment" in body
    assert "<table>" in body
    assert '<div class="code-block">' in body
    assert 'class="copy-btn"' in body
    assert '<span class="code-comment">' in body
