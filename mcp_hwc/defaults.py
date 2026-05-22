from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from .regions import normalize_region_input
from .sdk_service import resolve_service_spec

Intent = Literal["small", "balanced", "performance"]
Exposure = Literal["auto", "public", "private", "internal"]

_VALID_INTENTS = {"small", "balanced", "performance"}
_VALID_EXPOSURES = {"auto", "public", "private", "internal"}

_COMMON_DEFAULTS: dict[str, Any] = {
    "resource_reuse": {
        "reuse_tagged_defaults_first": True,
        "reuse_existing_when_safe": True,
        "create_if_missing": True,
        "managed_tags": {
            "managed-by": "mcp-hwc",
            "profile": "default",
        },
    },
    "network_profile": {
        "vpc": "default-or-managed",
        "subnet": "default-or-managed",
        "security_group": "service-profile",
    },
    "cost_policy": {
        "selection_strategy": "smallest-sane",
        "prefer_pay_per_use": True,
    },
    "result_focus": [
        "return the final endpoint, IP, or resource identifier first",
        "hide intermediate resource noise unless the user asked for it",
    ],
}

_SERVICE_DEFAULTS: dict[str, dict[str, Any]] = {
    "ecs": {
        "deployment_style": "vm",
        "workflow_tool": "ecs_create_vm",
        "defaults": {
            "image_preferences": ["Debian", "Ubuntu", "Huawei Cloud EulerOS"],
            "flavor_policy": {
                "preferred_families": ["c3", "ac8"],
                "min_vcpus": 2,
                "min_ram_mb": 4096,
            },
            "root_volume": {"type": "SSD", "size_gb": 40},
            "public_access": True,
            "security_profile": "ssh",
        },
        "readiness_checks": ["server ACTIVE", "public IP assigned", "SSH reachable"],
        "post_create_steps": ["ssh configuration", "package installation"],
    },
    "cce": {
        "deployment_style": "kubernetes",
        "defaults": {
            "cluster_version": "latest-stable",
            "node_pools": [
                {
                    "name": "default",
                    "node_count": 2,
                    "flavor_policy": {
                        "preferred_families": ["c6", "c7", "c3", "ac8"],
                        "min_vcpus": 2,
                        "min_ram_mb": 4096,
                    },
                }
            ],
            "addons": ["coredns", "cni", "metrics-server"],
            "public_api": False,
        },
        "readiness_checks": [
            "cluster available",
            "node pools ready",
            "kubeconfig retrievable",
        ],
        "post_create_steps": ["kubectl operations", "helm installations"],
    },
    "rds": {
        "deployment_style": "managed-database",
        "defaults": {
            "flavor_policy": {
                "selection_strategy": "smallest-sane",
                "min_vcpus": 2,
                "min_ram_mb": 4096,
            },
            "storage": {"type": "CLOUDSSD", "size_gb": 40},
            "backup_retention_days": 7,
            "public_access": False,
            "security_profile": "private-db",
        },
        "readiness_checks": ["instance running", "endpoint assigned"],
        "post_create_steps": ["connection test"],
    },
    "functiongraph": {
        "deployment_style": "serverless",
        "defaults": {
            "runtime_family_preferences": ["Python3.9", "Python3.10", "Node.js18.15"],
            "memory_size_mb": 128,
            "timeout_seconds": 30,
            "enable_lts_log": True,
        },
        "readiness_checks": ["function create/update success"],
        "post_create_steps": ["function invoke or trigger validation"],
    },
    "swr": {
        "deployment_style": "container-registry",
        "defaults": {
            "create_namespace_if_missing": True,
            "create_repository_if_missing": True,
            "repository_visibility": "private",
            "repository_category": "other",
        },
        "readiness_checks": ["repository exists", "push credentials issued"],
        "post_create_steps": ["container image push"],
    },
    "css": {
        "deployment_style": "managed-search",
        "defaults": {
            "public_access": False,
            "security_profile": "private-search",
            "backup_enabled": True,
        },
        "readiness_checks": ["cluster available", "endpoint assigned"],
        "post_create_steps": ["health check", "index or access validation"],
    },
    "dcs": {
        "deployment_style": "managed-cache",
        "defaults": {
            "public_access": False,
            "security_profile": "private-cache",
            "backup_enabled": True,
        },
        "readiness_checks": ["instance running", "endpoint assigned"],
        "post_create_steps": ["client connection validation"],
    },
}


def resolve_service_defaults(
    service_name: str,
    *,
    region: str | None = None,
    intent: str = "small",
    exposure: str = "auto",
) -> dict[str, object]:
    if intent not in _VALID_INTENTS:
        supported = ", ".join(sorted(_VALID_INTENTS))
        raise ValueError(f"Unsupported intent '{intent}'. Supported intents: {supported}")
    if exposure not in _VALID_EXPOSURES:
        supported = ", ".join(sorted(_VALID_EXPOSURES))
        raise ValueError(
            f"Unsupported exposure '{exposure}'. Supported exposures: {supported}"
        )

    resolved_spec = resolve_service_spec(service_name)
    normalized_region = normalize_region_input(region) if region else None

    profile = deepcopy(_COMMON_DEFAULTS)
    service_defaults = deepcopy(_SERVICE_DEFAULTS.get(resolved_spec.name, {}))
    profile.update(service_defaults)

    defaults = dict(profile.get("defaults", {}))
    if resolved_spec.name in {"ecs", "cce", "functiongraph"}:
        defaults["exposure"] = exposure
    if exposure != "auto" and resolved_spec.name in {"ecs", "rds", "css", "dcs"}:
        defaults["public_access"] = exposure == "public"
    if resolved_spec.name == "cce":
        defaults["public_api"] = exposure == "public"

    result = {
        "service": resolved_spec.name,
        "display_name": resolved_spec.display_name,
        "implementation": resolved_spec.implementation_name,
        "region": normalized_region,
        "intent": intent,
        "exposure": exposure,
        "deployment_style": profile.get("deployment_style", "generic"),
        "workflow_tool": profile.get("workflow_tool"),
        "minimal_tool_input": _minimal_tool_input(
            resolved_spec.name,
            region=normalized_region,
            exposure=exposure,
        ),
        "resource_reuse": profile["resource_reuse"],
        "network_profile": profile["network_profile"],
        "cost_policy": profile["cost_policy"],
        "defaults": _apply_intent_overrides(defaults, intent=intent),
        "readiness_checks": profile.get("readiness_checks", []),
        "post_create_steps": profile.get("post_create_steps", []),
        "result_focus": profile["result_focus"],
    }

    notes = [
        "Prefer the workflow_tool and minimal_tool_input when present; use generic SDK tools only for uncommon operations.",
        "The generic SDK tools remain available for exact API payload fields and advanced resource capabilities.",
    ]
    if normalized_region:
        notes.append(
            f"Region was normalized to {normalized_region}; region-specific flavor or addon filtering still requires live service inspection."
        )
    result["notes"] = notes
    return result


def _minimal_tool_input(
    service_name: str,
    *,
    region: str | None,
    exposure: str,
) -> dict[str, object] | None:
    if service_name == "ecs":
        payload: dict[str, object] = {
            "region": region or "<region>",
            "public_access": exposure != "private",
            "wait": False,
        }
        if exposure == "public":
            payload["ssh_cidr"] = "<your-ip>/32"
        return payload
    return None


def _apply_intent_overrides(defaults: dict[str, Any], *, intent: str) -> dict[str, Any]:
    resolved = deepcopy(defaults)

    root_volume = resolved.get("root_volume")
    if isinstance(root_volume, dict):
        if intent == "balanced":
            root_volume.setdefault("size_gb", 40)
            root_volume["size_gb"] = max(int(root_volume["size_gb"]), 60)
        elif intent == "performance":
            root_volume.setdefault("size_gb", 40)
            root_volume["size_gb"] = max(int(root_volume["size_gb"]), 100)

    storage = resolved.get("storage")
    if isinstance(storage, dict):
        if intent == "balanced":
            storage.setdefault("size_gb", 40)
            storage["size_gb"] = max(int(storage["size_gb"]), 100)
        elif intent == "performance":
            storage.setdefault("size_gb", 40)
            storage["size_gb"] = max(int(storage["size_gb"]), 200)

    node_pools = resolved.get("node_pools")
    if isinstance(node_pools, list):
        for node_pool in node_pools:
            if not isinstance(node_pool, dict):
                continue
            if intent == "balanced":
                node_pool["node_count"] = max(int(node_pool.get("node_count", 2)), 3)
            elif intent == "performance":
                node_pool["node_count"] = max(int(node_pool.get("node_count", 2)), 4)

    function_timeout = resolved.get("timeout_seconds")
    if isinstance(function_timeout, int):
        if intent == "balanced":
            resolved["timeout_seconds"] = max(function_timeout, 60)
        elif intent == "performance":
            resolved["timeout_seconds"] = max(function_timeout, 120)

    return resolved
