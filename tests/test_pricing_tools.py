from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from mcp_hwc.pricing.models import QuoteItem, QuoteResult, ResourceDescriptor
from mcp_hwc.pricing.persistence import QuoteStore


def test_resource_descriptor_from_tool_args() -> None:
    desc = ResourceDescriptor(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="month",
        period_num=1,
        quantity=2,
    )
    assert desc.service == "ecs"
    assert desc.quantity == 2


def test_quote_export_csv() -> None:
    from mcp_hwc.pricing.tools import export_csv

    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=(
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
        ),
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    csv_text = export_csv(result)
    lines = csv_text.strip().split("\n")
    assert len(lines) == 3
    assert "ecs" in lines[1]
    assert "rds" in lines[2]


def test_quote_export_terraform() -> None:
    from mcp_hwc.pricing.tools import export_terraform

    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=(
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
        ),
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    tf_text = export_terraform(result)
    assert "huaweicloud_compute_instance" in tf_text
    assert "100.0" in tf_text


@pytest.mark.anyio
async def test_pricing_tools_registered_in_mcp() -> None:
    from mcp_hwc.server import mcp
    from mcp_hwc.core.tool_manager import tool_manager

    await tool_manager.load_toolset(mcp, "pricing", force=True)

    tool_names = {t.name for t in await mcp.list_tools()}
    expected = {
        "price_quote",
        "price_discover",
        "price_export",
        "price_list_quotes",
        "price_get_quote",
        "price_share",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
