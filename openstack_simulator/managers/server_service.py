"""ServerCreationService: ``POST /servers`` rules for bare-metal nodes.

``create`` runs these steps in order; a failing step raises a ``SimError``
and skips every later one. No node, allocation, or quota state changes
before the Placement claim (step 7), and a failure after the claim rolls
the claim back.

1 auth and project, 2 schema validation, 3 lookup, 3b strict-mode
resource comparison, 4 quota, 5 availability zone, 6 scheduling,
7 claim and allocation, 8 deploy chain.

``ctx`` is duck-typed: ``project_id``, ``is_admin``, ``now`` and optionally
``microversion``, ``username``, ``debug``.
"""

from __future__ import annotations

import base64
import binascii
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .. import messages
from ..exceptions import (
    BadRequest,
    Conflict,
    Forbidden,
    InvalidState,
    ServerNotFound,
    FlavorNotAccessible,
    FlavorNotFound,
    ImageNotActive,
    ImageNotFound,
    InvalidAvailabilityZone,
    KeypairNotFound,
    NetworkNotFound,
    NoValidHost,
    SecurityGroupNotFound,
    SimError,
)
from ..models import Instance, PendingTransition, _generate_id, _now_timestamp
from ..sim_config import SimConfig
from ..traits import normalize_trait
from .scheduler import (
    SchedulingContext,
    flavor_resource_class,
    is_schedulable,
    pick,
)
from .transitions import pending_for, plan_deploy

USER_DATA_LIMIT = 64 * 1024
METADATA_LIMIT = 255
_AZ_NODE_PREFIX = "nova::"
_NAME_MAX = 255
_KEYPAIR_NAME_RE = re.compile(r"^[a-zA-Z0-9 _@.\-]{1,255}$")
_RESOURCE_SPEC_RE = re.compile(r"^resources:(CUSTOM_[A-Z0-9_]+)$")
_BDM_SOURCES = ("image", "volume", "snapshot", "blank")
_BDM_DESTINATIONS = ("local", "volume")
_HINT_STATES = ("enroll", "manageable")


# ---------------------------------------------------------------------------
# Flavor creation validation helpers (Requirement 9)
# ---------------------------------------------------------------------------


def validate_flavor_extra_specs(
    specs: Mapping[str, Any],
    cfg: SimConfig,
    baremetal: bool = False,
) -> dict[str, str]:
    """Validate and normalize the extra specs of a flavor being created.

    Returns a new dict where ``trait:<T>`` keys carry the normalized
    (uppercase) trait name. Raises ``BadRequest`` or ``InvalidTrait`` (400).
    ``baremetal`` marks a flavor that must carry a resource class when the
    ``require_resource_class`` guard is on.
    """
    result: dict[str, str] = {}
    has_class = False
    for key, value in (specs or {}).items():
        key = str(key)
        sval = str(value).strip() if value is not None else ""
        if key.startswith("hw:"):
            raise BadRequest(messages.baremetal_flavor_no_hw())
        if key.startswith("resources:"):
            if _RESOURCE_SPEC_RE.match(key):
                if sval != "1":
                    raise BadRequest(messages.invalid_resource_class_spec(key))
                has_class = True
            result[key] = sval
            continue
        if key.startswith("trait:"):
            name = normalize_trait(key[len("trait:"):])
            if sval == "forbidden" or (
                cfg.guards.require_trait_extra_spec_value and sval != "required"
            ):
                raise BadRequest(messages.invalid_trait_spec_value())
            result["trait:" + name] = sval
            continue
        result[key] = value
    if baremetal and cfg.guards.require_resource_class and not has_class:
        raise BadRequest(messages.missing_resource_class_spec())
    return result


# ---------------------------------------------------------------------------
# Create request
# ---------------------------------------------------------------------------


@dataclass
class CreateRequest:
    """Validated create request (also the ``request`` seen by the scheduler)."""

    id: str
    name: str
    flavor_ref: str
    image_ref: Optional[str]
    key_name: Optional[str] = None
    security_groups: list[str] = field(default_factory=list)
    networks: Any = None
    availability_zone: Optional[str] = None
    user_data: Optional[str] = None
    metadata: dict[str, str] = field(default_factory=dict)
    traits: list[str] = field(default_factory=list)
    config_drive: Any = None
    block_device_mapping_v2: list[dict] = field(default_factory=list)
    server_group: Optional[str] = None
    microversion: tuple = (2, 1)


def _pick(body: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if n in body:
            return body[n]
    return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class ServerCreationService:
    def __init__(
        self,
        store: Any,
        cfg: SimConfig,
        placement: Any,
        node_service: Any,
        quota_manager: Any,
        images: Any,
        lock: Any = None,
        debug: bool = False,
    ) -> None:
        self.store = store
        self.cfg = cfg
        self.placement = placement
        self.node_service = node_service
        self.quota = quota_manager
        self.images = images
        self.lock = lock if lock is not None else threading.RLock()
        self.debug = debug

    # -- delete and refresh -------------------------------------------------

    def _node_of(self, server: Any) -> Any:
        node_id = getattr(server, "node_id", None)
        if not node_id:
            return None
        return self.store.baremetal_nodes.get(node_id)

    def refresh(self, server: Instance) -> Instance:
        """Derive the status of a bare-metal server from its node.

        The caller runs ``NodeService.sync(now)`` first. The status stays
        ``BUILD`` until the node is ``active`` or ``deploy failed``. Legacy
        and deleted servers are returned as is.
        """
        if server.status == "DELETED" or not getattr(server, "node_id", None):
            return server
        with self.lock:
            node = self._node_of(server)
            if node is None or node.instance_uuid != server.id:
                return server
            if server.status == "BUILD":
                if node.provision_state == "active":
                    server.status = "ACTIVE"
                    server.task_state = None
                elif node.provision_state == "deploy failed":
                    server.status = "ERROR"
                    server.task_state = None
                    if not getattr(server, "fault", None):
                        server.fault = {
                            "message": messages.deploy_failed(node.last_error or ""),
                            "code": 500,
                            "created": _now_timestamp(),
                        }
            return server

    def delete(self, ctx: Any, server_id: str, force: bool = False) -> None:
        """Delete a server. Returns ``None`` (HTTP 204) on success."""
        with self.lock:
            server = self.store.instances.get(server_id)
            if server is None:
                for s in self.store.instances.values():
                    if s.id == server_id:
                        server = s
                        break
            project = getattr(ctx, "project_id", None)
            if server is None or (
                getattr(server, "project_id", None) not in (None, project)
                and not getattr(ctx, "is_admin", False)
            ):
                raise ServerNotFound(f"Instance {server_id} could not be found.")
            if server.status == "DELETED":
                return None  # repeated delete: 204, no second release

            node = self._node_of(server)
            if node is None:  # legacy virtual instance: old soft delete
                server.status = "DELETED"
                return None

            self.node_service.sync(ctx.now)
            if getattr(node, "protected", False):
                raise Conflict(f"Node {node.id} is protected")
            state = node.provision_state
            if state == "deploying" and not force:
                raise Conflict(messages.instance_locked())
            if node.instance_uuid != server.id:
                raise InvalidState(messages.invalid_state(state, node.id))

            if state == "deploying":
                node.provision_state = "deploy failed"
                node.target_provision_state = None
                verb = "clean"
            elif state in ("deploy failed", "clean failed"):
                verb = "clean"
            else:
                verb = "undeploy"
            pending = pending_for(node, verb, self.cfg, ctx.now)  # may raise
            node.target_provision_state = pending.final_state
            self.store.pending[node.id] = pending

            self.placement.release(server.id)
            server.status = "DELETED"  # releases quota usage
            server.task_state = None
            return None

    # -- step 1: auth and project -------------------------------------------

    def _resolve_project(self, ctx: Any, body: Mapping[str, Any]) -> str:
        project = getattr(ctx, "project_id", None)
        if not project:
            raise SimError(401, "unauthorized", "Authentication required")
        body_project = _pick(body, "project_id", "tenant_id")
        if (
            body_project is not None
            and body_project != project
            and not getattr(ctx, "is_admin", False)
        ):
            raise Forbidden(messages.project_mismatch())
        return project

    # -- step 2: schema validation -------------------------------------------

    def _validate(self, ctx: Any, body: Mapping[str, Any]) -> CreateRequest:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > _NAME_MAX:
            raise BadRequest("Invalid input for field/attribute name.")

        flavor_ref = _pick(body, "flavor_ref", "flavorRef")
        if not isinstance(flavor_ref, str) or not flavor_ref:
            raise BadRequest("Invalid input for field/attribute flavorRef.")

        bdm = _pick(body, "block_device_mapping_v2")
        bdm = [] if bdm is None else bdm
        if not isinstance(bdm, list):
            raise BadRequest("Invalid input for field/attribute block_device_mapping_v2.")
        for dev in bdm:
            if not isinstance(dev, dict):
                raise BadRequest(
                    "Invalid input for field/attribute block_device_mapping_v2."
                )
            src = dev.get("source_type")
            dst = dev.get("destination_type")
            if src is not None and src not in _BDM_SOURCES:
                raise BadRequest("Invalid input for field/attribute source_type.")
            if dst is not None and dst not in _BDM_DESTINATIONS:
                raise BadRequest("Invalid input for field/attribute destination_type.")
            if src in ("image", "volume", "snapshot") and not dev.get("uuid"):
                raise BadRequest("Invalid input for field/attribute uuid.")

        image_ref = _pick(body, "image_ref", "imageRef")
        if image_ref is None or image_ref == "":
            if not bdm:
                raise BadRequest("Invalid input for field/attribute imageRef.")
            image_ref = None
        elif not isinstance(image_ref, str):
            raise BadRequest("Invalid input for field/attribute imageRef.")

        networks = body.get("networks")
        if networks is not None:
            if isinstance(networks, str):
                if networks not in ("auto", "none"):
                    raise BadRequest("Invalid input for field/attribute networks.")
            elif isinstance(networks, list):
                for net in networks:
                    if not isinstance(net, dict):
                        raise BadRequest("Invalid input for field/attribute networks.")
            else:
                raise BadRequest("Invalid input for field/attribute networks.")

        key_name = body.get("key_name")
        if key_name is not None and (
            not isinstance(key_name, str) or not _KEYPAIR_NAME_RE.match(key_name)
        ):
            raise BadRequest("Invalid input for field/attribute key_name.")

        user_data = body.get("user_data")
        if user_data is not None:
            if not isinstance(user_data, str) or len(user_data) >= USER_DATA_LIMIT:
                raise BadRequest("Invalid input for field/attribute user_data.")
            try:
                base64.b64decode(user_data, validate=True)
            except (binascii.Error, ValueError):
                raise BadRequest("Invalid input for field/attribute user_data.")

        metadata = body.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise BadRequest("Invalid input for field/attribute metadata.")
        for k, v in metadata.items():
            if (
                not isinstance(k, str)
                or not isinstance(v, str)
                or not (1 <= len(k) <= METADATA_LIMIT)
                or len(v) > METADATA_LIMIT
            ):
                raise BadRequest("Invalid input for field/attribute metadata.")

        traits: list[str] = []
        if "traits" in body:
            if not self.cfg.features.microversion_traits_field:
                raise BadRequest("Additional properties are not allowed ('traits' was unexpected)")
            raw = body["traits"]
            if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
                raise BadRequest("Invalid input for field/attribute traits.")
            traits = [normalize_trait(t) for t in raw]

        sgs: list[str] = []
        raw_sgs = body.get("security_groups")
        if raw_sgs is not None:
            if not isinstance(raw_sgs, list):
                raise BadRequest("Invalid input for field/attribute security_groups.")
            for sg in raw_sgs:
                ref = sg.get("name") if isinstance(sg, dict) else sg
                if not isinstance(ref, str) or not ref:
                    raise BadRequest("Invalid input for field/attribute security_groups.")
                sgs.append(ref)

        az = body.get("availability_zone")
        if az is not None and not isinstance(az, str):
            raise BadRequest("Invalid input for field/attribute availability_zone.")

        hints = body.get("scheduler_hints") or body.get("os:scheduler_hints") or {}
        group = hints.get("group") if isinstance(hints, dict) else None

        micro = getattr(ctx, "microversion", None) or (2, 1)
        return CreateRequest(
            id=_generate_id(),
            name=name,
            flavor_ref=flavor_ref,
            image_ref=image_ref,
            key_name=key_name,
            security_groups=sgs,
            networks=networks,
            availability_zone=az,
            user_data=user_data,
            metadata=dict(metadata),
            traits=traits,
            config_drive=body.get("config_drive"),
            block_device_mapping_v2=list(bdm),
            server_group=group if isinstance(group, str) else None,
            microversion=tuple(micro),
        )

    # -- step 3: lookup -----------------------------------------------------

    def _find_flavor(self, ref: str) -> Any:
        flavors = self.store.flavors
        flavor = flavors.get(ref)
        if flavor is None:
            for f in flavors.values():
                if f.name == ref:
                    return f
        return flavor

    def _lookup(self, ctx: Any, project: str, req: CreateRequest) -> tuple[Any, Any]:
        flavor = self._find_flavor(req.flavor_ref)
        if flavor is None:
            raise FlavorNotFound(messages.flavor_not_found(req.flavor_ref))
        if not flavor.is_public:
            allowed = set(flavor.access) | set(
                self.store.flavor_access.get(flavor.id, ())
            )
            if project not in allowed:
                raise FlavorNotAccessible(
                    messages.flavor_not_accessible(flavor.id, project)
                )
        if any(str(k).startswith("hw:") for k in flavor.extra_specs):
            raise BadRequest(messages.baremetal_flavor_no_hw())

        image = None
        if req.image_ref is not None:
            image = self.images.get_visible(req.image_ref, project)
            if image is None:
                raise ImageNotFound(messages.image_not_found(req.image_ref))
            if not self.images.is_active(image):
                raise ImageNotActive(messages.image_not_active(req.image_ref))
            if not self.images.has_resolvable_kernel_ramdisk(image):
                raise BadRequest(messages.image_requires_kernel_ramdisk())

        if req.key_name is not None:
            kp = self.store.keypairs.get(req.key_name)
            if kp is None or _attr(kp, "project_id", project) not in (project, None):
                user = getattr(ctx, "username", None) or project
                raise KeypairNotFound(messages.keypair_not_found(req.key_name, user))

        for ref in req.security_groups:
            sg = self._find_security_group(ref)
            if sg is None or _attr(sg, "project_id", project) not in (project, None):
                raise SecurityGroupNotFound(
                    messages.security_group_not_found(ref, project)
                )

        if isinstance(req.networks, list):
            for net in req.networks:
                ref = net.get("uuid") or net.get("network")
                if ref is None:
                    continue
                found = self._find_network(ref)
                if found is None or not self._network_usable(found, project):
                    raise NetworkNotFound(messages.network_not_found(ref))

        if req.server_group is not None:
            groups = getattr(self.store, "server_groups", {}) or {}
            group = groups.get(req.server_group)
            if group is None or _attr(group, "project_id", project) not in (
                project,
                None,
            ):
                raise BadRequest(messages.server_group_invalid(req.server_group))
        return flavor, image

    def _find_security_group(self, ref: str) -> Any:
        sgs = self.store.security_groups
        if ref in sgs:
            return sgs[ref]
        for sg in sgs.values():
            if sg.id == ref or sg.name == ref:
                return sg
        return None

    def _find_network(self, ref: str) -> Any:
        nets = self.store.networks
        if ref in nets:
            return nets[ref]
        for net in nets.values():
            if net.id == ref or net.name == ref:
                return net
        return None

    @staticmethod
    def _network_usable(net: Any, project: str) -> bool:
        if _attr(net, "status") == "DELETED":
            return False
        if _attr(net, "shared", False):
            return True
        return _attr(net, "project_id", project) in (project, None)

    # -- step 3b: strict-mode comparison ------------------------------------

    def _strict_check(self, flavor: Any, req: CreateRequest, nodes: list[Any]) -> None:
        if not self.cfg.strict_mode:
            return
        pool = self._az_pool(req, nodes)
        if pool is None:
            rc = flavor_resource_class(flavor)
            pool = [
                n
                for n in nodes
                if rc is None or self._node_class(n) == rc
            ]
        if not pool:
            return
        if all(
            flavor.ram > n.memory_mb
            or flavor.vcpus > n.cpus
            or flavor.disk > n.local_gb
            for n in pool
        ):
            raise BadRequest(
                "Flavor's resources exceed the capacity of the available bare metal nodes."
            )

    @staticmethod
    def _node_class(node: Any) -> Optional[str]:
        rc = node.resource_class
        if not rc:
            return None
        rc = "".join(c if c.isalnum() else "_" for c in str(rc).upper())
        return rc if rc.startswith("CUSTOM_") else "CUSTOM_" + rc

    @staticmethod
    def _az_node_id(req: CreateRequest) -> Optional[str]:
        az = req.availability_zone
        if az and az.startswith(_AZ_NODE_PREFIX):
            return az[len(_AZ_NODE_PREFIX):]
        return None

    def _az_pool(self, req: CreateRequest, nodes: list[Any]) -> Optional[list[Any]]:
        target = self._az_node_id(req)
        if target is None:
            return None
        return [n for n in nodes if n.id == target]

    # -- step 5: availability zone ------------------------------------------

    def _candidates(self, req: CreateRequest, nodes: list[Any]) -> list[Any]:
        target = self._az_node_id(req)
        if target is None:
            return list(nodes)
        found = [n for n in nodes if n.id == target]
        if not found:
            raise InvalidAvailabilityZone(messages.invalid_availability_zone(target))
        return found

    # -- create -------------------------------------------------------------

    def create(self, ctx: Any, body: Mapping[str, Any]) -> Instance:
        if isinstance(body, Mapping) and isinstance(body.get("server"), Mapping):
            body = body["server"]
        if not isinstance(body, Mapping):
            raise BadRequest("Invalid request body.")

        project = self._resolve_project(ctx, body)  # step 1
        req = self._validate(ctx, body)  # step 2

        with self.lock:
            flavor, image = self._lookup(ctx, project, req)  # step 3
            nodes = self.node_service.sync(ctx.now)
            self._strict_check(flavor, req, nodes)  # step 3b
            self.quota.check_create(project, flavor)  # step 4
            candidates = self._candidates(req, nodes)  # step 5
            return self._schedule_and_claim(
                ctx, project, req, flavor, image, candidates
            )

    def _schedule_and_claim(
        self,
        ctx: Any,
        project: str,
        req: CreateRequest,
        flavor: Any,
        image: Any,
        candidates: list[Any],
    ) -> Instance:
        for node in candidates:
            self.placement.ensure_provider(node)
        providers = self.placement.snapshot()

        passing: dict[str, Any] = {}
        for node in candidates:
            sctx = SchedulingContext(
                guards=self.cfg.guards,
                features=self.cfg.features,
                strict_mode=self.cfg.strict_mode,
                provider=providers.get(node.id),
                az=req.availability_zone,
                microversion=req.microversion,
            )
            if is_schedulable(node, flavor, req, image, project, sctx).ok:
                passing[node.id] = node

        rc = flavor_resource_class(flavor)
        for node_id in pick(list(passing), self.cfg.seed, req.name):  # step 6
            node = passing[node_id]
            if rc is not None and not self.placement.claim(node.id, req.id, rc):
                continue  # step 7 lost the race; try the next candidate
            try:
                return self._allocate(ctx, project, req, flavor, image, node)
            except BaseException:
                self.placement.release(req.id)
                raise
        debug = self.debug or bool(getattr(ctx, "debug", False))
        raise self._no_valid_host(candidates, debug)

    def _no_valid_host(self, candidates: list[Any], debug: bool) -> NoValidHost:
        details = None
        if (
            self.cfg.strict_mode
            and debug
            and len(candidates) == 1
            and candidates[0].provision_state in _HINT_STATES
        ):
            node = candidates[0]
            details = messages.node_hint(node.id, node.provision_state)
        return NoValidHost(details=details)

    def _allocate(
        self,
        ctx: Any,
        project: str,
        req: CreateRequest,
        flavor: Any,
        image: Any,
        node: Any,
    ) -> Instance:
        """Steps 7 and 8 under the lock. On error, restore the node and the
        store; the caller releases the claim."""
        saved = (node.instance_uuid, node.target_provision_state)
        prev_pending = self.store.pending.get(node.id)
        added_instance = False
        try:
            steps = plan_deploy(self.cfg, ctx.now)
            pending = PendingTransition(
                node_id=node.id,
                steps=steps,
                verb="deploy",
                final_state="active",
                server_id=req.id,
            )
            server = Instance(
                id=req.id,
                name=req.name,
                flavor=flavor.id,
                image=req.image_ref or "",
                status="BUILD",
                created_at=_now_timestamp(),
                project_id=project,
                node_id=node.id,
                task_state="spawning",
                flavor_vcpus=flavor.vcpus,
                flavor_ram=flavor.ram,
                flavor_disk=flavor.disk,
                availability_zone=req.availability_zone,
                traits=list(req.traits),
            )
            node.instance_uuid = req.id
            node.target_provision_state = "active"
            self.store.pending[node.id] = pending
            self.store.instances[server.id] = server
            added_instance = True
            return server
        except BaseException:
            node.instance_uuid, node.target_provision_state = saved
            if prev_pending is None:
                self.store.pending.pop(node.id, None)
            else:
                self.store.pending[node.id] = prev_pending
            if added_instance:
                self.store.instances.pop(req.id, None)
            raise
