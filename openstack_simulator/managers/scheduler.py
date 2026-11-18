"""Pure scheduler for bare-metal server creation.

``is_schedulable`` decides whether one node can host a create request. It
reads only its arguments: no store, clock, or global random state, and it
never mutates its inputs. Placement data arrives through ``ctx.provider``, a
``ProviderView`` (duck typed: ``uuid``, ``parent``, ``inventory``,
``traits``, ``allocations``; see ``managers/placement.py``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Optional

from ..exceptions import InvalidTrait
from ..sim_config import Features, Guards
from ..traits import normalize_trait

TRAITS_FIELD_MIN_MICROVERSION = (2, 78)
_RC_SPEC_PREFIX = "resources:"
_TRAIT_SPEC_PREFIX = "trait:"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: Optional[str] = None  # failing check id, e.g. "maintenance"


@dataclass(frozen=True)
class SchedulingContext:
    guards: Guards
    features: Features
    strict_mode: bool
    provider: Any  # ProviderView | None
    az: Optional[str] = None
    microversion: tuple = (2, 1)


_OK = Verdict(True)


def _fail(reason: str) -> Verdict:
    return Verdict(False, reason)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or an object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm_trait(raw: str) -> str:
    try:
        return normalize_trait(raw)
    except InvalidTrait:
        return str(raw).strip().upper()


def flavor_resource_class(flavor: Any) -> Optional[str]:
    """Return ``CUSTOM_<CLASS>`` from a ``resources:CUSTOM_<CLASS>=1`` extra spec."""
    specs = _get(flavor, "extra_specs", None) or {}
    for key in sorted(specs):
        if key.startswith(_RC_SPEC_PREFIX + "CUSTOM_") and str(specs[key]).strip() == "1":
            return key[len(_RC_SPEC_PREFIX):]
    return None


def _node_resource_class(node: Any) -> Optional[str]:
    rc = _get(node, "resource_class")
    if not rc:
        return None
    rc = "".join(c if c.isalnum() else "_" for c in str(rc).upper())
    return rc if rc.startswith("CUSTOM_") else "CUSTOM_" + rc


def required_traits(flavor: Any, request: Any, ctx: SchedulingContext) -> frozenset:
    """Flavor ``trait:<T>=required`` specs plus request traits (microversion >= 2.78)."""
    required = set()
    specs = _get(flavor, "extra_specs", None) or {}
    for key, value in specs.items():
        if key.startswith(_TRAIT_SPEC_PREFIX) and str(value).strip() == "required":
            required.add(_norm_trait(key[len(_TRAIT_SPEC_PREFIX):]))
    if (
        ctx.features.microversion_traits_field
        and tuple(ctx.microversion) >= TRAITS_FIELD_MIN_MICROVERSION
    ):
        for trait in _get(request, "traits", None) or []:
            required.add(_norm_trait(trait))
    return frozenset(required)


def _inventory_ok(provider: Any, rc: str) -> bool:
    inv = _get(provider, "inventory", None) or {}
    item = inv.get(rc)
    if item is None:
        return False
    return (
        _get(item, "total") == 1
        and _get(item, "reserved") == 0
        and float(_get(item, "allocation_ratio", 1.0)) == 1.0
    )


def _az_ok(node: Any, provider: Any, az: Optional[str]) -> bool:
    """A ``nova::<uuid>`` zone must designate this node's own provider."""
    if not az or not az.startswith("nova::"):
        return True
    target = az[len("nova::"):]
    return target == _get(node, "id") and _get(provider, "uuid", target) == target


def _node_arch(node: Any) -> Optional[str]:
    props = _get(node, "properties", None) or {}
    return props.get("cpu_arch") or _get(node, "cpu_arch")


def _image_arch(image: Any) -> Optional[str]:
    arch = _get(image, "hw_architecture")
    if arch is None:
        arch = (_get(image, "properties", None) or {}).get("hw_architecture")
    return arch


def _same_arch(a: Any, b: Any) -> bool:
    return str(a).lower() == str(b).lower()


def is_schedulable(node, flavor, request, image, project, ctx: SchedulingContext) -> Verdict:
    """Return the verdict for ``node``; the first failing check wins."""
    guards, features = ctx.guards, ctx.features

    if _get(node, "provision_state") != "available":
        return _fail("provision_state")
    if _get(node, "instance_uuid") is not None:
        return _fail("instance_uuid")
    if _get(node, "maintenance"):
        return _fail("maintenance")
    if _get(node, "target_provision_state") is not None:
        return _fail("target_provision_state")
    if guards.enforce_conductor and _get(node, "conductor") is None:
        return _fail("conductor")
    if _get(node, "last_error") is not None:
        return _fail("last_error")
    if features.protected_field and _get(node, "protected"):
        return _fail("protected")

    flavor_rc = flavor_resource_class(flavor)
    if flavor_rc is None:
        if guards.require_resource_class:
            return _fail("resource_class")
    elif _node_resource_class(node) != flavor_rc:
        return _fail("resource_class")

    if flavor_rc is not None:
        provider = ctx.provider
        if provider is None or not _inventory_ok(provider, flavor_rc):
            return _fail("placement_inventory")
        own = _get(request, "id")
        allocations = _get(provider, "allocations", None) or {}
        if any(consumer != own for consumer in allocations):
            return _fail("placement_inventory")
        if not _az_ok(node, provider, ctx.az):
            return _fail("placement_inventory")

    required = required_traits(flavor, request, ctx)
    if required:
        node_traits = {_norm_trait(t) for t in (_get(node, "traits", None) or [])}
        if not node_traits or not required <= node_traits:
            return _fail("traits")

    if guards.enforce_cpu_arch:
        node_arch = _node_arch(node)
        specs = _get(flavor, "extra_specs", None) or {}
        flavor_arch = specs.get("capabilities:cpu_arch")
        if flavor_arch is not None and not _same_arch(flavor_arch, node_arch):
            return _fail("cpu_arch")
        img_arch = _image_arch(image)
        if img_arch is not None and not _same_arch(img_arch, node_arch):
            return _fail("image_arch")

    if _get(flavor, "disk", 0) > (_get(node, "local_gb", 0) or 0):
        return _fail("flavor_disk")

    if guards.enforce_owner:
        owner = _get(node, "owner")
        if owner is not None and owner != project:
            return _fail("owner")
    if guards.enforce_lessee:
        lessee = _get(node, "lessee")
        if lessee is not None and lessee != project:
            return _fail("lessee")

    return _OK


def pick(candidates: list, seed: int, request_key: str) -> list:
    """Deterministic candidate order for ``seed`` and ``request_key``.

    Sorts by uuid, then shuffles with a private ``random.Random``; the first
    element is the preferred node, the rest are fallbacks if a claim fails.
    """
    ordered = sorted(candidates)
    random.Random(f"{seed}:{request_key}").shuffle(ordered)
    return ordered
