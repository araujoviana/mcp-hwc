from __future__ import annotations

import pytest

from mcp_hwc.pricing.catalog import (
    CLOUD_SERVICE_TYPES,
    RESOURCE_TYPES,
    SERVICE_MAP,
    resolve_cloud_service_type,
    resolve_resource_type,
    resolve_region,
)


def test_resolve_cloud_service_type_known() -> None:
    assert resolve_cloud_service_type("ecs") == "hws.service.type.ec2"


def test_resolve_cloud_service_type_case_insensitive() -> None:
    assert resolve_cloud_service_type("ECS") == "hws.service.type.ec2"


def test_resolve_cloud_service_type_unknown() -> None:
    with pytest.raises(ValueError, match="unknown service"):
        resolve_cloud_service_type("foobar")


def test_resolve_resource_type_known() -> None:
    assert resolve_resource_type("ecs") == "hws.resource.type.ec2"


def test_resolve_resource_type_differs_from_cloud_service_type() -> None:
    assert resolve_cloud_service_type("ecs") != resolve_resource_type("ecs")


def test_resolve_region_alias() -> None:
    assert resolve_region("sao paulo") == "sa-brazil-1"


def test_resolve_region_code_passthrough() -> None:
    assert resolve_region("sa-brazil-1") == "sa-brazil-1"


def test_service_map_has_expected_keys() -> None:
    expected = {"ecs", "evs", "vpc", "eip", "elb", "rds", "obs", "cce"}
    assert expected.issubset(set(SERVICE_MAP.keys()))


def test_cloud_service_types_and_resource_types_have_same_keys() -> None:
    assert set(CLOUD_SERVICE_TYPES.keys()) == set(RESOURCE_TYPES.keys())
