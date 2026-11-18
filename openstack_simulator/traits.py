"""Trait helpers: normalization and validation of Placement/Ironic trait names."""

import re

from .exceptions import InvalidTrait

TRAIT_RE = re.compile(r"^[A-Z0-9_]{1,255}$")

# Subset of os-traits bundled as a constant.
STANDARD_TRAITS: frozenset = frozenset(
    {
        "HW_CPU_X86_AVX",
        "HW_CPU_X86_AVX2",
        "HW_CPU_X86_AVX512F",
        "HW_CPU_X86_SSE42",
        "HW_CPU_X86_AESNI",
        "HW_CPU_X86_VMX",
        "HW_CPU_X86_SVM",
        "HW_CPU_X86_MMX",
        "HW_CPU_X86_SSE",
        "HW_CPU_X86_SSE2",
        "HW_CPU_X86_SSE3",
        "HW_CPU_X86_SSSE3",
        "HW_CPU_X86_SSE41",
        "HW_CPU_X86_FMA3",
        "HW_CPU_X86_BMI",
        "HW_CPU_X86_BMI2",
        "HW_CPU_X86_AMD_SVM",
        "HW_CPU_HYPERTHREADING",
        "HW_NIC_SRIOV",
        "HW_NIC_OFFLOAD_TSO",
        "HW_GPU_API_VULKAN",
        "STORAGE_DISK_SSD",
        "STORAGE_DISK_HDD",
        "COMPUTE_NET_ATTACH_INTERFACE",
        "COMPUTE_VOLUME_ATTACH",
        "COMPUTE_STATUS_DISABLED",
        "COMPUTE_NODE",
        "COMPUTE_TRUSTED_CERTS",
        "COMPUTE_IMAGE_TYPE_RAW",
        "COMPUTE_IMAGE_TYPE_QCOW2",
        "COMPUTE_IMAGE_TYPE_ISO",
        "MISC_SHARES_VIA_AGGREGATE",
    }
)

CUSTOM_PREFIX = "CUSTOM_"


def normalize_trait(raw: str) -> str:
    """Return the upper-cased, stripped trait name or raise InvalidTrait (400)."""
    if not isinstance(raw, str):
        raise InvalidTrait(f"Invalid trait: {raw!r}")
    trait = raw.strip().upper()
    if not TRAIT_RE.match(trait):
        raise InvalidTrait(f"Invalid trait: {raw!r}")
    if not (trait.startswith(CUSTOM_PREFIX) or trait in STANDARD_TRAITS):
        raise InvalidTrait(f"Invalid trait: {raw!r}")
    return trait
