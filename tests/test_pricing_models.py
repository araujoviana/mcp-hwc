from __future__ import annotations

import uuid
from datetime import datetime, timezone

from mcp_hwc.pricing.models import QuoteItem, QuoteResult, ResourceDescriptor


def test_resource_descriptor_defaults() -> None:
    desc = ResourceDescriptor(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="on_demand",
    )
    assert desc.period_num == 1
    assert desc.quantity == 1


def test_resource_descriptor_rejects_invalid_period_type() -> None:
    import pytest

    with pytest.raises(ValueError, match="period_type"):
        ResourceDescriptor(
            service="ecs",
            spec="c6.large.2",
            region="sa-brazil-1",
            period_type="weekly",
        )


def test_quote_item_total_price() -> None:
    item = QuoteItem(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="month",
        period_num=1,
        quantity=2,
        unit_price=100.0,
        currency="USD",
    )
    assert item.total_price == 200.0


def test_quote_result_monthly_and_annual() -> None:
    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=[
            QuoteItem(
                service="ecs",
                spec="c6.large.2",
                region="sa-brazil-1",
                period_type="month",
                period_num=1,
                quantity=1,
                unit_price=100.0,
                currency="USD",
            ),
        ],
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    assert result.total_monthly == 100.0
    assert result.total_annual == 1200.0


def test_quote_result_on_demand_monthly_from_hourly() -> None:
    import pytest

    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=[
            QuoteItem(
                service="ecs",
                spec="c6.large.2",
                region="sa-brazil-1",
                period_type="on_demand",
                period_num=1,
                quantity=1,
                unit_price=0.15,
                currency="USD",
            ),
        ],
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    assert result.total_monthly == pytest.approx(0.15 * 730, rel=1e-6)
    assert result.total_annual == pytest.approx(0.15 * 730 * 12, rel=1e-6)


def test_quote_result_to_dict_round_trip() -> None:
    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=[
            QuoteItem(
                service="rds",
                spec="mysql.ha.xlarge.4",
                region="sa-brazil-1",
                period_type="year",
                period_num=1,
                quantity=1,
                unit_price=5000.0,
                currency="USD",
            ),
        ],
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    data = result.to_dict()
    assert data["currency"] == "USD"
    assert len(data["items"]) == 1
    assert data["items"][0]["service"] == "rds"
