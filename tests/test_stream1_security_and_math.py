from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

import pytest

from mcp_hwc.cloud_services.cli_service import CliService, CliServiceError, _sanitize_command
from mcp_hwc.core.config import CloudApiConfig, ObsConfig
from mcp_hwc.pricing.bss_pricing import BssPricingBackend
from mcp_hwc.pricing.models import QuoteItem, QuoteResult, ResourceDescriptor
from mcp_hwc.workflows.lts_workflow import normalize_time_ms


def test_cloud_api_config_repr_masks_secret() -> None:
    config = CloudApiConfig(
        access_key_id="DEMO_AK_12345",
        secret_access_key="SUPER_SECRET_SK_ABCDEF123456",
        region="sa-brazil-1",
    )
    repr_str = repr(config)
    assert "SUPER_SECRET_SK" not in repr_str
    assert "***" in repr_str
    assert "DEMO_AK_12345" in repr_str


def test_obs_config_repr_masks_secret() -> None:
    config = ObsConfig(
        access_key_id="DEMO_AK_12345",
        secret_access_key="SUPER_SECRET_SK_ABCDEF123456",
    )
    repr_str = repr(config)
    assert "SUPER_SECRET_SK" not in repr_str
    assert "***" in repr_str


def test_sanitize_command_masks_passwords() -> None:
    cmd = [
        "docker",
        "run",
        "-e",
        "PGPASSWORD=supersecret",
        "-e",
        "NORMAL=value",
        "postgres:16",
        "-p",
        "mypassword",
    ]
    sanitized = _sanitize_command(cmd)
    assert "supersecret" not in sanitized
    assert "mypassword" not in sanitized
    assert "PGPASSWORD=***" in sanitized


def test_pricing_multi_year_amortization_math() -> None:
    # 3-year subscription for $3,600 total (for 1 unit) -> monthly should be $100.0/mo
    item = QuoteItem(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="year",
        period_num=3,
        quantity=1,
        unit_price=3600.0,
        currency="USD",
    )
    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=(item,),
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    assert result.total_monthly == pytest.approx(100.0)
    assert result.total_annual == pytest.approx(1200.0)


def test_pricing_resolve_quote_items_avoids_quadratic_multiplication() -> None:
    # 5 instances rated by BSS at $500 total for the batch
    desc = ResourceDescriptor(
        service="ecs",
        spec="c6.large.2",
        region="sa-brazil-1",
        period_type="month",
        period_num=1,
        quantity=5,
    )

    class FakeResult:
        id = "0"
        official_website_amount = 500.0

    items = BssPricingBackend._resolve_quote_items([FakeResult()], [desc])
    assert len(items) == 1
    assert items[0].quantity == 5
    # Unit price should be $100, so total_price is $500 (not $2500!)
    assert items[0].unit_price == pytest.approx(100.0)
    assert items[0].total_price == pytest.approx(500.0)


def test_normalize_time_ms_accepts_float() -> None:
    now_f = time.time()
    res = normalize_time_ms(now_f, default=datetime.now(timezone.utc))
    assert res.isdigit()
    assert int(res) > 10**12
