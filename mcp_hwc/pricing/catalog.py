from __future__ import annotations

from mcp_hwc.regions import normalize_region_input

CLOUD_SERVICE_TYPES: dict[str, str] = {
    "ecs": "hws.service.type.ec2",
    "evs": "hws.service.type.evs",
    "vpc": "hws.service.type.vpc",
    "eip": "hws.service.type.eip",
    "elb": "hws.service.type.elb",
    "nat": "hws.service.type.nat",
    "rds": "hws.service.type.rds",
    "dds": "hws.service.type.dds",
    "dcs": "hws.service.type.dcs",
    "dms": "hws.service.type.dms",
    "obs": "hws.service.type.obs",
    "sfs": "hws.service.type.sfs",
    "cce": "hws.service.type.cce",
    "functiongraph": "hws.service.type.functiongraph",
    "kms": "hws.service.type.kms",
    "smn": "hws.service.type.smn",
    "ces": "hws.service.type.ces",
    "dns": "hws.service.type.dns",
    "waf": "hws.service.type.waf",
    "cdn": "hws.service.type.cdn",
}

RESOURCE_TYPES: dict[str, str] = {
    "ecs": "hws.resource.type.ec2",
    "evs": "hws.resource.type.evs",
    "vpc": "hws.resource.type.vpc",
    "eip": "hws.resource.type.eip",
    "elb": "hws.resource.type.elb",
    "nat": "hws.resource.type.nat",
    "rds": "hws.resource.type.rds",
    "dds": "hws.resource.type.dds",
    "dcs": "hws.resource.type.dcs",
    "dms": "hws.resource.type.dms",
    "obs": "hws.resource.type.obs",
    "sfs": "hws.resource.type.sfs",
    "cce": "hws.resource.type.cce",
    "functiongraph": "hws.resource.type.functiongraph",
    "kms": "hws.resource.type.kms",
    "smn": "hws.resource.type.smn",
    "ces": "hws.resource.type.ces",
    "dns": "hws.resource.type.dns",
    "waf": "hws.resource.type.waf",
    "cdn": "hws.resource.type.cdn",
}

SERVICE_MAP = CLOUD_SERVICE_TYPES


def _resolve(service: str, mapping: dict[str, str], label: str) -> str:
    key = service.strip().lower()
    code = mapping.get(key)
    if code is None:
        known = ", ".join(sorted(mapping.keys()))
        raise ValueError(f"unknown service '{service}'. Known services: {known}")
    return code


def resolve_cloud_service_type(service: str) -> str:
    return _resolve(service, CLOUD_SERVICE_TYPES, "cloud_service_type")


def resolve_resource_type(service: str) -> str:
    return _resolve(service, RESOURCE_TYPES, "resource_type")


def resolve_region(region: str) -> str:
    return normalize_region_input(region)
