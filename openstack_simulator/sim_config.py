"""Simulator behavior configuration (``conf/simulator.yaml``).

Priority, highest first: constructor overrides, YAML file, defaults.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


class ConfigError(ValueError):
    """Invalid simulator configuration. The message names the dotted key."""


@dataclass(frozen=True)
class Timings:
    """Transition durations in seconds, before time scaling."""

    enroll_to_verifying: float = 2
    verifying_to_manageable: float = 5
    cleaning: float = 30
    deploy: float = 45
    undeploy: float = 5
    cleaning_after_delete: float = 30
    power: float = 3
    inspect: float = 10


@dataclass(frozen=True)
class Guards:
    require_resource_class: bool = True
    require_trait_extra_spec_value: bool = True
    enforce_owner: bool = True
    enforce_lessee: bool = True
    enforce_conductor: bool = True
    enforce_pxe_port: bool = True
    enforce_cpu_arch: bool = True
    enforce_quota: bool = True


@dataclass(frozen=True)
class Features:
    microversion_traits_field: bool = True
    protected_field: bool = False
    deleting_state: bool = True


@dataclass(frozen=True)
class SimConfig:
    time_scale: float = 1.0
    strict_mode: bool = True
    seed: int = 42
    timings: Timings = field(default_factory=Timings)
    guards: Guards = field(default_factory=Guards)
    features: Features = field(default_factory=Features)

    def duration(self, name: str) -> float:
        """Configured timing ``name`` multiplied by ``time_scale``."""
        try:
            base = getattr(self.timings, name)
        except AttributeError:
            raise KeyError(f"unknown timing: {name}") from None
        return base * self.time_scale


# section name in YAML -> (SimConfig attribute or None for top-level, dataclass)
_SECTIONS: dict[str, tuple[Optional[str], type]] = {
    "simulator": (None, SimConfig),
    "timings_seconds": ("timings", Timings),
    "guards": ("guards", Guards),
    "features": ("features", Features),
}
_SIMULATOR_KEYS = ("time_scale", "strict_mode", "seed")
# Accepted aliases for override section prefixes.
_SECTION_ALIASES = {"timings": "timings_seconds"}


def default_sim_config_path() -> Path:
    """``<project>/conf/simulator.yaml``, else ``/app/conf/simulator.yaml``."""
    path = Path(__file__).resolve().parent.parent / "conf" / "simulator.yaml"
    if not path.exists():
        path = Path("/app/conf/simulator.yaml")
    return path


def _validate(dotted: str, name: str, value: Any, kind: str) -> Any:
    if kind == "bool":
        if not isinstance(value, bool):
            raise ConfigError(f"{dotted}: expected boolean, got {value!r}")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{dotted}: expected integer, got {value!r}")
        return value
    # number
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{dotted}: expected number, got {value!r}")
    if not math.isfinite(value):
        raise ConfigError(f"{dotted}: expected finite number, got {value!r}")
    if value < 0:
        raise ConfigError(f"{dotted}: must be >= 0, got {value!r}")
    return value


def _kind(section: str, key: str) -> Optional[str]:
    """Value kind for a key of a section, or None if the key is unknown."""
    if section == "simulator":
        return {"time_scale": "number", "strict_mode": "bool", "seed": "int"}.get(key)
    cls = _SECTIONS[section][1]
    if key not in {f.name for f in fields(cls)}:
        return None
    return "number" if section == "timings_seconds" else "bool"


def _resolve_flat_key(key: str) -> Optional[tuple[str, str]]:
    """Map a flat or dotted override key to ``(section, key)``."""
    if "." in key:
        section, _, name = key.partition(".")
        section = _SECTION_ALIASES.get(section, section)
        if section in _SECTIONS and _kind(section, name):
            return section, name
        return None
    for section in _SECTIONS:
        if _kind(section, key):
            return section, key
    return None


def _apply(values: dict[tuple[str, str], Any], section: str, key: str, value: Any) -> None:
    dotted = f"{section}.{key}"
    values[(section, key)] = _validate(dotted, key, value, _kind(section, key))  # type: ignore[arg-type]


def _read_file(path: Path, values: dict[tuple[str, str], Any]) -> None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if data is None:
        return
    if not isinstance(data, Mapping):
        raise ConfigError(f"{path}: expected a mapping at top level")
    for section in _SECTIONS:
        if section not in data or data[section] is None:
            continue
        body = data[section]
        if not isinstance(body, Mapping):
            raise ConfigError(f"{section}: expected a mapping")
        for key, value in body.items():
            if _kind(section, str(key)) is None:
                continue  # unknown keys are ignored
            _apply(values, section, str(key), value)


def load_sim_config(
    path: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None
) -> SimConfig:
    """Load the configuration.

    ``path`` defaults to the standard lookup; a missing file yields defaults.
    ``overrides`` may use flat (``time_scale``) or dotted (``guards.enforce_owner``)
    keys and wins over the file. Unrelated override keys are ignored.
    Raises ConfigError naming the dotted key on invalid values.
    """
    if path is None:
        path = default_sim_config_path()
    path = Path(path)

    values: dict[tuple[str, str], Any] = {}
    if path.is_file():
        _read_file(path, values)
    for key, value in (overrides or {}).items():
        resolved = _resolve_flat_key(str(key))
        if resolved is not None:
            _apply(values, resolved[0], resolved[1], value)

    top: dict[str, Any] = {}
    sub: dict[str, dict[str, Any]] = {"timings": {}, "guards": {}, "features": {}}
    for (section, key), value in values.items():
        attr = _SECTIONS[section][0]
        if attr is None:
            top[key] = value
        else:
            sub[attr][key] = value

    cfg = SimConfig()
    return replace(
        cfg,
        **top,
        timings=replace(cfg.timings, **sub["timings"]),
        guards=replace(cfg.guards, **sub["guards"]),
        features=replace(cfg.features, **sub["features"]),
    )
