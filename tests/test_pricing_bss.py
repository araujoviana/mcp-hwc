from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_hwc.pricing.bss_pricing import BssAccessDenied, BssPricingBackend, PricingNotAvailable
from mcp_hwc.pricing.models import ResourceDescriptor


def test_period_type_mapping() -> None:
    backend = BssPricingBackend.__new__(BssPricingBackend)
    assert backend._map_period_type("month") == 2
    assert backend._map_period_type("year") == 3


def test_period_type_on_demand_raises() -> None:
    backend = BssPricingBackend.__new__(BssPricingBackend)
    with pytest.raises(ValueError, match="on_demand"):
        backend._map_period_type("on_demand")


def test_build_period_product_info() -> None:
    backend = BssPricingBackend.__new__(BssPricingBackend)
    desc = ResourceDescriptor(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="month",
        period_num=1,
        quantity=2,
    )
    info = backend._build_period_product_info(desc, index=0)
    assert info.id == "0"
    assert info.cloud_service_type == "hws.service.type.ec2"
    assert info.resource_type == "hws.resource.type.ec2"
    assert info.resource_spec == "c6.large.2"
    assert info.region == "sa-brazil-1"
    assert info.period_type == 2
    assert info.period_num == 1
    assert info.subscription_num == 2


def test_build_demand_product_info() -> None:
    backend = BssPricingBackend.__new__(BssPricingBackend)
    desc = ResourceDescriptor(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="on_demand",
        quantity=1,
    )
    info = backend._build_demand_product_info(desc, index=0)
    assert info.id == "0"
    assert info.cloud_service_type == "hws.service.type.ec2"
    assert info.resource_type == "hws.resource.type.ec2"
    assert info.usage_value == 1.0
    assert info.usage_measure_id == 1


def test_call_api_raises_bss_access_denied_on_403() -> None:
    exc = Exception("CBC.0156 Access denied")
    with pytest.raises(BssAccessDenied):
        BssPricingBackend._call_api(lambda req: (_ for _ in ()).throw(exc), None)


def test_call_api_raises_pricing_not_available_on_other_error() -> None:
    exc = Exception("Some other error")
    with pytest.raises(PricingNotAvailable):
        BssPricingBackend._call_api(lambda req: (_ for _ in ()).throw(exc), None)
