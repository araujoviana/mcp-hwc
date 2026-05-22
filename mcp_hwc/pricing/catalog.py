from __future__ import annotations

from mcp_hwc.regions import normalize_region_input

SERVICE_MAP: dict[str, str] = {
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


def resolve_cloud_service_type(service: str) -> str:
    key = service.strip().lower()
    code = SERVICE_MAP.get(key)
    if code is None:
        known = ", ".join(sorted(SERVICE_MAP.keys()))
        raise ValueError(f"unknown service '{service}'. Known services: {known}")
    return code


def resolve_resource_type(service: str) -> str:
    return resolve_cloud_service_type(service)


def resolve_region(region: str) -> str:
    return normalize_region_input(region)
