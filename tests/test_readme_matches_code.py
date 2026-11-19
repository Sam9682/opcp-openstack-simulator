"""Bug condition exploration: README.md must match the code.

The page served at ``/`` is README.md rendered to HTML, so checking the README
covers both. Facts are extracted from the code (routes, ``Simulator``
attributes, manager signatures, compose services, repository layout) and each
one must appear in the README.

On unfixed code these tests are EXPECTED TO FAIL. Each failure is a
counterexample showing that the README is out of date.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.11**
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openstack_simulator import Simulator
from openstack_simulator.api.app import create_app
from openstack_simulator.managers.baremetal import BaremetalManager

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

_SERVICE_PREFIXES = (
    "/_sim",
    "/identity",
    "/compute",
    "/network",
    "/volume",
    "/baremetal",
    "/image",
)


def _normalize(path: str) -> str:
    """Replace ``<conv:name>`` and ``{name}`` placeholders with ``*``."""
    path = re.sub(r"<[^>]+>", "*", path)
    return re.sub(r"\{[^}]+\}", "*", path)


def _section(heading: str) -> str:
    """Return README text from ``heading`` up to the next heading of equal or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = README.splitlines()
    out: list[str] = []
    inside = False
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("#"):
            hashes = len(line) - len(line.lstrip("#"))
            if line.strip() == heading:
                inside = True
                continue
            if inside and hashes <= level:
                break
        if inside:
            out.append(line)
    return "\n".join(out)


def _collect_routes() -> list[str]:
    app = create_app({"time_scale": 0})
    rules = {
        _normalize(r.rule)
        for r in app.url_map.iter_rules()
        if r.rule.startswith(_SERVICE_PREFIXES)
    }
    return sorted(rules)


ROUTES = _collect_routes()
README_NORMALIZED = _normalize(README)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rule", ROUTES)
def test_route_is_documented(rule: str) -> None:
    assert rule in README_NORMALIZED, f"route {rule} missing from README"


# --------------------------------------------------------------------------
# Simulator attributes
# --------------------------------------------------------------------------
SIM_ATTRS = sorted(a for a in vars(Simulator({"time_scale": 0})) if not a.startswith("_"))


@pytest.mark.parametrize("attr", SIM_ATTRS)
def test_simulator_attribute_is_documented(attr: str) -> None:
    assert f"sim.{attr}" in README, f"Simulator attribute sim.{attr} missing from README"


# --------------------------------------------------------------------------
# BaremetalManager signatures
# --------------------------------------------------------------------------
def _baremetal_manager_section() -> str:
    return _section("### BaremetalManager")


@pytest.mark.parametrize("method", ["create_node", "update_node", "patch_node"])
def test_baremetal_manager_signature_matches(method: str) -> None:
    params = [
        p for p in inspect.signature(getattr(BaremetalManager, method)).parameters if p != "self"
    ]
    section = _baremetal_manager_section()
    lines = [ln for ln in section.splitlines() if f"{method}(" in ln]
    assert lines, f"BaremetalManager.{method} not documented in README"
    documented = " ".join(lines)
    missing = [p for p in params if not re.search(rf"\b{re.escape(p)}\b", documented)]
    assert not missing, f"{method} README signature lacks parameters {missing}; code has {params}"


def test_create_node_signature_has_uuid() -> None:
    """The fixed code takes ``uuid=None`` on create_node."""
    params = inspect.signature(BaremetalManager.create_node).parameters
    assert "uuid" in params and params["uuid"].default is None


# --------------------------------------------------------------------------
# docker-compose.yml services
# --------------------------------------------------------------------------
def _compose_services() -> list[str]:
    services: list[str] = []
    in_services = False
    for line in (ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        if line.startswith("services:"):
            in_services = True
            continue
        if in_services:
            m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if m:
                services.append(m.group(1))
            elif line and not line.startswith(" "):
                break
    return services


@pytest.mark.parametrize("service", _compose_services())
def test_compose_service_is_documented(service: str) -> None:
    assert service in README, f"compose service {service} missing from README"


# --------------------------------------------------------------------------
# Project tree
# --------------------------------------------------------------------------
def _tree_paths() -> list[str]:
    block = _section("## Project Structure")
    m = re.search(r"```[^\n]*\n(.*?)```", block, re.S)
    assert m, "Project Structure code block not found"
    stack: list[str] = []
    paths: list[str] = []
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        idx = re.search(r"[A-Za-z0-9_.]", line)
        if not idx:
            continue
        depth = idx.start() // 4
        name = line[idx.start():].split()[0]
        stack = stack[:depth]
        is_dir = name.endswith("/")
        stack.append(name.rstrip("/"))
        if depth == 0:
            continue
        rel = "/".join(stack[1:])
        paths.append(rel + ("/" if is_dir else ""))
    return paths


TREE = _tree_paths()


@pytest.mark.parametrize("rel", [p for p in TREE if p.rstrip("/") != "ssl"])
def test_tree_path_exists_on_disk(rel: str) -> None:
    assert (ROOT / rel.rstrip("/")).exists(), f"README tree lists {rel} but it is absent"


def _repo_files() -> list[str]:
    files = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "openstack_simulator").rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    files += [
        p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("*.py")
    ]
    files.append("conf/simulator.yaml")
    return sorted(files)


@pytest.mark.parametrize("rel", _repo_files())
def test_file_is_in_tree(rel: str) -> None:
    assert rel in TREE, f"{rel} exists but is not in the README project tree"


# --------------------------------------------------------------------------
# Wording
# --------------------------------------------------------------------------
def test_image_is_not_described_as_stub() -> None:
    assert not re.search(r"image[^\n]*\bstub\b", README, re.I)


def test_no_snapshot_or_bond_rest_routes_claimed() -> None:
    app = create_app({"time_scale": 0})
    rules = [r.rule for r in app.url_map.iter_rules()]
    endpoints = _section("## API Endpoints")
    for word in ("snapshot", "bond"):
        if any(word in r for r in rules):
            continue
        for line in endpoints.splitlines():
            if word in line.lower():
                assert "manager" in line.lower(), (
                    f"README endpoint table claims '{word}' but no such REST route exists: {line.strip()}"
                )


# --------------------------------------------------------------------------
# Baremetal node UUID documentation (Property 4)
# --------------------------------------------------------------------------
def test_readme_documents_node_uuid_generation() -> None:
    assert re.search(
        r"(generat\w*|random)[^\n]*uuid|uuid[^\n]*(generat\w*|random)", README, re.I
    ), "no mention of node UUID generation"


@pytest.mark.parametrize("cmd", ["node create", "node show", "node list"])
def test_readme_shows_uuid_in_cli_output(cmd: str) -> None:
    assert f"openstack baremetal {cmd}" in README, f"'openstack baremetal {cmd}' not shown"
    assert re.search(r"uuid", README, re.I), "UUID never mentioned"


def test_readme_documents_optional_uuid_field() -> None:
    lines = [ln for ln in README.splitlines() if re.search(r"uuid", ln, re.I)]
    text = "\n".join(lines)
    assert re.search(r"optional[^\n]*uuid|uuid[^\n]*optional|--uuid", text, re.I), (
        "optional `uuid` field not documented"
    )
    assert "400" in text and "malformed" in text.lower(), "400 for malformed uuid not documented"
    assert "409" in text and "duplicate" in text.lower() or "already exists" in text.lower(), (
        "409 for duplicate uuid not documented"
    )
