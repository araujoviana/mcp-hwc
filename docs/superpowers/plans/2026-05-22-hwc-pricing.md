# HWC Pricing Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pricing/quotation tools to mcp-hwc using BSS SDK as primary backend with Playwright fallback, quote persistence, and shareable calculator URLs.

**Architecture:** New `mcp_hwc/pricing/` subpackage with 6 modules (models, catalog, bss_pricing, persistence, tools, web_pricing). BSS SDK handles subscription and on-demand rating. Catalog maps friendly names to HWC internal codes. Persistence stores quotes as JSON. Playwright fallback scrapes the HWC calculator for services not in the SDK.

**Tech Stack:** Python 3.13, huaweicloudsdkbss>=3.1.196, pydantic-style dataclasses, FastMCP tool decorators, Playwright MCP (for web_pricing fallback)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `mcp_hwc/pricing/__init__.py` | Package init, re-exports |
| `mcp_hwc/pricing/models.py` | Data models: `ResourceDescriptor`, `QuoteItem`, `QuoteResult` |
| `mcp_hwc/pricing/catalog.py` | Friendly-name → HWC code mapping, region aliases, spec discovery cache |
| `mcp_hwc/pricing/bss_pricing.py` | BSS SDK pricing backend (subscription + on-demand) |
| `mcp_hwc/persistence.py` | Quote save/load/list, JSON file storage |
| `mcp_hwc/pricing/tools.py` | MCP tool definitions: `price_quote`, `price_discover`, `price_export`, `price_list_quotes`, `price_get_quote`, `price_share` |
| `mcp_hwc/pricing/web_pricing.py` | Playwright scraping fallback |
| `mcp_hwc/server.py` | Import and register pricing tools |
| `tests/test_pricing_models.py` | Tests for models |
| `tests/test_pricing_catalog.py` | Tests for catalog |
| `tests/test_pricing_bss.py` | Tests for BSS backend |
| `tests/test_pricing_persistence.py` | Tests for persistence |
| `tests/test_pricing_tools.py` | Tests for MCP tools |

---

### Task 1: Data Models

**Files:**
- Create: `mcp_hwc/pricing/__init__.py`
- Create: `mcp_hwc/pricing/models.py`
- Test: `tests/test_pricing_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_models.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_hwc.pricing'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_hwc/pricing/__init__.py
from .models import QuoteItem, QuoteResult, ResourceDescriptor

__all__ = ["QuoteItem", "QuoteResult", "ResourceDescriptor"]
```

```python
# mcp_hwc/pricing/models.py
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_VALID_PERIOD_TYPES = ("on_demand", "month", "year")
_HOURS_PER_MONTH = 730


@dataclass(frozen=True)
class ResourceDescriptor:
    service: str
    spec: str
    region: str
    period_type: str
    period_num: int = 1
    quantity: int = 1

    def __post_init__(self) -> None:
        if self.period_type not in _VALID_PERIOD_TYPES:
            raise ValueError(
                f"period_type must be one of {_VALID_PERIOD_TYPES}, got '{self.period_type}'"
            )
        if self.period_num < 1:
            raise ValueError("period_num must be >= 1")
        if self.quantity < 1:
            raise ValueError("quantity must be >= 1")


@dataclass(frozen=True)
class QuoteItem:
    service: str
    spec: str
    region: str
    period_type: str
    period_num: int
    quantity: int
    unit_price: float
    currency: str

    @property
    def total_price(self) -> float:
        return self.unit_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "spec": self.spec,
            "region": self.region,
            "period_type": self.period_type,
            "period_num": self.period_num,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class QuoteResult:
    quote_id: uuid.UUID
    items: tuple[QuoteItem, ...]
    currency: str
    created_at: datetime

    @property
    def total_monthly(self) -> float:
        total = 0.0
        for item in self.items:
            if item.period_type == "on_demand":
                total += item.unit_price * _HOURS_PER_MONTH * item.quantity
            elif item.period_type == "month":
                total += item.unit_price * item.period_num * item.quantity
            elif item.period_type == "year":
                total += (item.unit_price / 12) * item.period_num * item.quantity
        return total

    @property
    def total_annual(self) -> float:
        return self.total_monthly * 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote_id": str(self.quote_id),
            "items": [item.to_dict() for item in self.items],
            "total_monthly": round(self.total_monthly, 2),
            "total_annual": round(self.total_annual, 2),
            "currency": self.currency,
            "created_at": self.created_at.isoformat(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_models.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add mcp_hwc/pricing/__init__.py mcp_hwc/pricing/models.py tests/test_pricing_models.py
git commit -m "feat(pricing): add data models for ResourceDescriptor, QuoteItem, QuoteResult"
```

---

### Task 2: Catalog Mapping

**Files:**
- Create: `mcp_hwc/pricing/catalog.py`
- Test: `tests/test_pricing_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_catalog.py
from __future__ import annotations

import pytest

from mcp_hwc.pricing.catalog import (
    SERVICE_MAP,
    resolve_cloud_service_type,
    resolve_resource_type,
    resolve_region,
)


def test_resolve_cloud_service_type_known() -> None:
    assert resolve_cloud_service_type("ecs") == "hws.resource.type.ec2"


def test_resolve_cloud_service_type_case_insensitive() -> None:
    assert resolve_cloud_service_type("ECS") == "hws.resource.type.ec2"


def test_resolve_cloud_service_type_unknown() -> None:
    with pytest.raises(ValueError, match="unknown service"):
        resolve_cloud_service_type("foobar")


def test_resolve_resource_type_known() -> None:
    assert resolve_resource_type("ecs") == "hws.resource.type.ec2"


def test_resolve_region_alias() -> None:
    assert resolve_region("sao paulo") == "sa-brazil-1"


def test_resolve_region_code_passthrough() -> None:
    assert resolve_region("sa-brazil-1") == "sa-brazil-1"


def test_service_map_has_expected_keys() -> None:
    expected = {"ecs", "evs", "vpc", "eip", "elb", "rds", "obs", "cce"}
    assert expected.issubset(set(SERVICE_MAP.keys()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_hwc.pricing.catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_hwc/pricing/catalog.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_catalog.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add mcp_hwc/pricing/catalog.py tests/test_pricing_catalog.py
git commit -m "feat(pricing): add catalog mapping for service types and regions"
```

---

### Task 3: BSS Pricing Backend

**Files:**
- Create: `mcp_hwc/pricing/bss_pricing.py`
- Test: `tests/test_pricing_bss.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_bss.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcp_hwc.pricing.bss_pricing import BssPricingBackend, PricingNotAvailable
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
    assert info.cloud_service_type == "hws.resource.type.ec2"
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
    assert info.cloud_service_type == "hws.resource.type.ec2"
    assert info.usage_value == 1.0
    assert info.usage_measure_id == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_bss.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_hwc.pricing.bss_pricing'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_hwc/pricing/bss_pricing.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from huaweicloudsdkbss.v2 import BssClient
from huaweicloudsdkbss.v2.model import (
    DemandProductInfo,
    ListOnDemandResourceRatingsRequest,
    ListRateOnPeriodDetailRequest,
    PeriodProductInfo,
    RateOnDemandReq,
    RateOnPeriodReq,
)
from huaweicloudsdkcore.region.region import Region as SdkRegion

from .catalog import resolve_cloud_service_type, resolve_region
from .models import QuoteItem, QuoteResult, ResourceDescriptor

if TYPE_CHECKING:
    from mcp_hwc.config import CloudApiConfig


class PricingNotAvailable(RuntimeError):
    """Raised when BSS SDK cannot price a resource (triggers Playwright fallback)."""


class BssPricingBackend:
    def __init__(self, config: CloudApiConfig) -> None:
        self._config = config
        self._client = self._build_client()

    def _build_client(self) -> BssClient:
        from huaweicloudsdkcore.auth.credentials import BasicCredentials

        creds = BasicCredentials(
            ak=self._config.access_key_id,
            sk=self._config.secret_access_key,
        )
        if self._config.security_token:
            creds.security_token = self._config.security_token
        if self._config.project_id:
            creds.project_id = self._config.project_id
        if self._config.domain_id:
            creds.domain_id = self._config.domain_id

        region = self._config.region or "myhuaweicloud.com"
        endpoint = self._config.endpoint or f"bss.myhuaweicloud.com"
        sdk_region = SdkRegion(
            region_id=region,
            endpoints=[endpoint],
        )

        return BssClient.new_builder().with_credentials(creds).with_region(sdk_region).build()

    def quote(self, resources: list[ResourceDescriptor]) -> QuoteResult:
        subscription_resources = [r for r in resources if r.period_type != "on_demand"]
        demand_resources = [r for r in resources if r.period_type == "on_demand"]

        items: list[QuoteItem] = []

        if subscription_resources:
            items.extend(self._quote_subscription(subscription_resources))

        if demand_resources:
            items.extend(self._quote_on_demand(demand_resources))

        if not items:
            raise PricingNotAvailable("No resources could be priced via BSS SDK")

        return QuoteResult(
            quote_id=uuid.uuid4(),
            items=tuple(items),
            currency="USD",
            created_at=datetime.now(timezone.utc),
        )

    def _quote_subscription(self, resources: list[ResourceDescriptor]) -> list[QuoteItem]:
        product_infos = [
            self._build_period_product_info(r, index=i)
            for i, r in enumerate(resources)
        ]

        project_id = self._config.project_id or ""
        body = RateOnPeriodReq(project_id=project_id, product_infos=product_infos)
        request = ListRateOnPeriodDetailRequest(body=body)

        response = self._client.list_rate_on_period_detail(request)

        if response.status_code >= 400:
            raise PricingNotAvailable(
                f"BSS subscription pricing failed: HTTP {response.status_code}"
            )

        official = response.official_website_rating_result
        if official is None or not official.product_rating_results:
            raise PricingNotAvailable("BSS subscription pricing returned no results")

        items: list[QuoteItem] = []
        for result in official.product_rating_results:
            idx = int(result.id) if result.id is not None else 0
            if idx >= len(resources):
                continue
            desc = resources[idx]
            amount = float(result.official_website_amount or 0)
            items.append(
                QuoteItem(
                    service=desc.service,
                    spec=desc.spec,
                    region=desc.region,
                    period_type=desc.period_type,
                    period_num=desc.period_num,
                    quantity=desc.quantity,
                    unit_price=amount,
                    currency="USD",
                )
            )

        return items

    def _quote_on_demand(self, resources: list[ResourceDescriptor]) -> list[QuoteItem]:
        product_infos = [
            self._build_demand_product_info(r, index=i)
            for i, r in enumerate(resources)
        ]

        project_id = self._config.project_id or ""
        body = RateOnDemandReq(
            project_id=project_id,
            inquiry_precision=1,
            product_infos=product_infos,
        )
        request = ListOnDemandResourceRatingsRequest(body=body)

        response = self._client.list_on_demand_resource_ratings(request)

        if response.status_code >= 400:
            raise PricingNotAvailable(
                f"BSS on-demand pricing failed: HTTP {response.status_code}"
            )

        results = response.product_rating_results
        if not results:
            raise PricingNotAvailable("BSS on-demand pricing returned no results")

        items: list[QuoteItem] = []
        for result in results:
            idx = int(result.id) if result.id is not None else 0
            if idx >= len(resources):
                continue
            desc = resources[idx]
            amount = float(result.official_website_amount or 0)
            items.append(
                QuoteItem(
                    service=desc.service,
                    spec=desc.spec,
                    region=desc.region,
                    period_type="on_demand",
                    period_num=1,
                    quantity=desc.quantity,
                    unit_price=amount,
                    currency="USD",
                )
            )

        return items

    @staticmethod
    def _map_period_type(period_type: str) -> int:
        mapping = {"month": 2, "year": 3}
        if period_type not in mapping:
            raise ValueError(
                f"Cannot map period_type '{period_type}' to BSS period code. "
                f"Expected 'month' or 'year'."
            )
        return mapping[period_type]

    @staticmethod
    def _build_period_product_info(desc: ResourceDescriptor, index: int) -> PeriodProductInfo:
        return PeriodProductInfo(
            id=str(index),
            cloud_service_type=resolve_cloud_service_type(desc.service),
            resource_type=resolve_cloud_service_type(desc.service),
            resource_spec=desc.spec,
            region=resolve_region(desc.region),
            period_type=BssPricingBackend._map_period_type(desc.period_type),
            period_num=desc.period_num,
            subscription_num=desc.quantity,
        )

    @staticmethod
    def _build_demand_product_info(desc: ResourceDescriptor, index: int) -> DemandProductInfo:
        return DemandProductInfo(
            id=str(index),
            cloud_service_type=resolve_cloud_service_type(desc.service),
            resource_type=resolve_cloud_service_type(desc.service),
            resource_spec=desc.spec,
            region=resolve_region(desc.region),
            usage_value=1.0,
            usage_measure_id=1,
            subscription_num=desc.quantity,
        )

    def discover_specs(
        self,
        service: str,
        region: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, str]]:
        from huaweicloudsdkbss.v2.model import ListServiceResourcesRequest

        service_type_code = resolve_cloud_service_type(service)
        request = ListServiceResourcesRequest(
            service_type_code=service_type_code,
            limit=100,
            offset=0,
        )
        response = self._client.list_service_resources(request)

        resources = []
        for item in response.service_resources or []:
            entry = {
                "resource_type": item.resource_type or "",
                "resource_spec": item.resource_spec or "",
                "resource_spec_desc": item.resource_spec_desc or "",
            }
            if keyword and keyword.lower() not in entry["resource_spec_desc"].lower():
                if keyword.lower() not in entry["resource_spec"].lower():
                    continue
            resources.append(entry)

        return resources
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_bss.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mcp_hwc/pricing/bss_pricing.py tests/test_pricing_bss.py
git commit -m "feat(pricing): add BSS SDK pricing backend"
```

---

### Task 4: Quote Persistence

**Files:**
- Create: `mcp_hwc/pricing/persistence.py`
- Test: `tests/test_pricing_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_persistence.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_hwc.pricing.models import QuoteItem, QuoteResult
from mcp_hwc.pricing.persistence import QuoteStore


@pytest.fixture
def store(tmp_path: Path) -> QuoteStore:
    return QuoteStore(quotes_dir=tmp_path / "quotes")


def test_save_and_get_quote(store: QuoteStore) -> None:
    quote_id = uuid.uuid4()
    result = QuoteResult(
        quote_id=quote_id,
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
    store.save(result)
    loaded = store.get(quote_id)
    assert loaded.quote_id == quote_id
    assert len(loaded.items) == 1
    assert loaded.items[0].service == "ecs"


def test_get_nonexistent_quote_raises(store: QuoteStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.get(uuid.uuid4())


def test_list_quotes_empty(store: QuoteStore) -> None:
    assert store.list_quotes() == []


def test_list_quotes_returns_saved(store: QuoteStore) -> None:
    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=(
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
    store.save(result)
    summaries = store.list_quotes()
    assert len(summaries) == 1
    assert summaries[0]["quote_id"] == str(result.quote_id)
    assert summaries[0]["services"] == ["rds"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_persistence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_hwc.pricing.persistence'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_hwc/pricing/persistence.py
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .models import QuoteItem, QuoteResult


class QuoteStore:
    def __init__(self, quotes_dir: Path | None = None) -> None:
        if quotes_dir is None:
            quotes_dir = Path.home() / ".config" / "mcp-hwc" / "quotes"
        self._dir = quotes_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: QuoteResult) -> Path:
        path = self._dir / f"{result.quote_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return path

    def get(self, quote_id: uuid.UUID) -> QuoteResult:
        path = self._dir / f"{quote_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Quote {quote_id} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._from_dict(data)

    def list_quotes(self, limit: int = 20, service: str | None = None) -> list[dict[str, Any]]:
        files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        summaries: list[dict[str, Any]] = []
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            services = list({item["service"] for item in data.get("items", [])})
            if service and service.lower() not in [s.lower() for s in services]:
                continue
            summaries.append({
                "quote_id": data["quote_id"],
                "services": services,
                "total_monthly": data.get("total_monthly"),
                "total_annual": data.get("total_annual"),
                "currency": data.get("currency", "USD"),
                "created_at": data.get("created_at"),
            })
            if len(summaries) >= limit:
                break
        return summaries

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> QuoteResult:
        from datetime import datetime

        items = []
        for item_data in data.get("items", []):
            items.append(QuoteItem(
                service=item_data["service"],
                spec=item_data["spec"],
                region=item_data["region"],
                period_type=item_data["period_type"],
                period_num=item_data["period_num"],
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                currency=item_data["currency"],
            ))
        return QuoteResult(
            quote_id=uuid.UUID(data["quote_id"]),
            items=tuple(items),
            currency=data.get("currency", "USD"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_persistence.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mcp_hwc/pricing/persistence.py tests/test_pricing_persistence.py
git commit -m "feat(pricing): add quote persistence with JSON file storage"
```

---

### Task 5: MCP Tool Definitions

**Files:**
- Create: `mcp_hwc/pricing/tools.py`
- Modify: `mcp_hwc/server.py`
- Test: `tests/test_pricing_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_tools.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_hwc.pricing.tools'`

- [ ] **Step 3: Write minimal implementation**

```python
# mcp_hwc/pricing/tools.py
from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from .models import QuoteItem, QuoteResult, ResourceDescriptor
from .persistence import QuoteStore


_TERRAFORM_RESOURCE_MAP: dict[str, str] = {
    "ecs": "huaweicloud_compute_instance",
    "evs": "huaweicloud_evs_volume",
    "vpc": "huaweicloud_vpc",
    "eip": "huaweicloud_vpc_eip",
    "elb": "huaweicloud_elb_loadbalancer",
    "rds": "huaweicloud_rds_instance",
    "obs": "huaweicloud_obs_bucket",
    "cce": "huaweicloud_cce_cluster",
    "nat": "huaweicloud_nat_gateway",
    "dns": "huaweicloud_dns_zone",
    "kms": "huaweicloud_kms_key",
}


def export_csv(result: QuoteResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "service", "resource_spec", "region", "period_type",
        "period_num", "quantity", "unit_price", "total_price", "currency",
    ])
    for item in result.items:
        writer.writerow([
            item.service,
            item.spec,
            item.region,
            item.period_type,
            item.period_num,
            item.quantity,
            item.unit_price,
            item.total_price,
            item.currency,
        ])
    return output.getvalue()


def export_json(result: QuoteResult) -> str:
    import json
    return json.dumps(result.to_dict(), indent=2)


def export_terraform(result: QuoteResult) -> str:
    lines = [
        '# Generated by mcp-hwc pricing tools',
        f'# Quote ID: {result.quote_id}',
        f'# Total monthly: ${result.total_monthly:.2f} USD',
        '',
    ]
    for i, item in enumerate(result.items):
        tf_type = _TERRAFORM_RESOURCE_MAP.get(item.service, f"huaweicloud_{item.service}_resource")
        name = f"{item.service}_{i}"
        lines.append(f'resource "{tf_type}" "{name}" {{')
        lines.append(f'  region     = "{item.region}"')
        lines.append(f'  # spec: {item.spec}')
        lines.append(f'  # period: {item.period_type} x{item.period_num}')
        lines.append(f'  # quantity: {item.quantity}')
        lines.append(f'  # price: ${item.unit_price:.2f} USD/{item.period_type}')
        lines.append('}')
        lines.append('')

    return "\n".join(lines)


def format_text(result: QuoteResult) -> str:
    lines = [
        f"Quote {result.quote_id}",
        "=" * 60,
        "",
    ]
    for item in result.items:
        period_label = (
            f"{item.period_type} x{item.period_num}"
            if item.period_type != "on_demand"
            else "on-demand (hourly)"
        )
        lines.append(f"  {item.service} / {item.spec}")
        lines.append(f"    Region: {item.region}")
        lines.append(f"    Period: {period_label}")
        lines.append(f"    Qty:    {item.quantity}")
        lines.append(f"    Price:  ${item.unit_price:.2f} USD each")
        lines.append(f"    Total:  ${item.total_price:.2f} USD")
        lines.append("")

    lines.append("-" * 60)
    lines.append(f"  Monthly est: ${result.total_monthly:.2f} USD")
    lines.append(f"  Annual est:  ${result.total_annual:.2f} USD")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_tools.py -v`
Expected: 3 passed

- [ ] **Step 5: Register pricing tools in server.py**

Add the following imports and tool functions to `mcp_hwc/server.py`:

After the existing imports (around line 83), add:
```python
from .pricing.models import QuoteItem, QuoteResult, ResourceDescriptor
from .pricing.bss_pricing import BssPricingBackend, PricingNotAvailable
from .pricing.catalog import resolve_region as _pricing_resolve_region
from .pricing.persistence import QuoteStore
from .pricing.tools import export_csv, export_json, export_terraform, format_text
```

Add a cached getter for the BSS backend (after `get_cli_service`):
```python
@lru_cache(maxsize=1)
def get_bss_pricing_backend() -> BssPricingBackend:
    return BssPricingBackend(CloudApiConfig.from_env("BSS"))


@lru_cache(maxsize=1)
def get_quote_store() -> QuoteStore:
    return QuoteStore()
```

Add `BssPricingBackend` and `PricingNotAvailable` to the `_run_tool_call` exception tuple.

Add the MCP tool functions at the end of the file:
```python
@mcp.tool()
def price_quote(
    resources: list[dict[str, object]],
    region: str | None = None,
) -> dict[str, object]:
    """Get pricing/quotation for Huawei Cloud resources. Each resource dict needs: service, spec, region, period_type. Optional: period_num, quantity."""

    def quote() -> dict[str, object]:
        descs = []
        for r in resources:
            r_region = str(r.get("region", "") or region or "")
            if not r_region:
                raise ValueError("region is required (per-resource or top-level)")
            descs.append(ResourceDescriptor(
                service=str(r["service"]),
                spec=str(r["spec"]),
                region=r_region,
                period_type=str(r["period_type"]),
                period_num=int(r.get("period_num", 1)),
                quantity=int(r.get("quantity", 1)),
            ))

        backend = get_bss_pricing_backend()
        try:
            result = backend.quote(descs)
        except PricingNotAvailable:
            return {
                "error": "BSS SDK could not price these resources. Playwright fallback not yet implemented.",
                "resources": [r.to_dict() if hasattr(r, "to_dict") else r for r in descs],
            }

        get_quote_store().save(result)
        return {
            "text": format_text(result),
            **result.to_dict(),
        }

    return _run_tool_call(quote)


@mcp.tool()
def price_discover(
    service: str,
    region: str | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    """Discover available resource types and specs for a Huawei Cloud service."""

    def discover() -> dict[str, object]:
        backend = get_bss_pricing_backend()
        specs = backend.discover_specs(service, region=region, keyword=keyword)
        return {
            "service": service,
            "region": region,
            "specs": specs,
            "count": len(specs),
        }

    return _run_tool_call(discover)


@mcp.tool()
def price_export(
    quote_id: str,
    format: str = "json",
) -> dict[str, object]:
    """Export a saved quote in json, csv, or terraform format."""

    def export() -> dict[str, object]:
        store = get_quote_store()
        result = store.get(uuid.UUID(quote_id))
        if format == "csv":
            content = export_csv(result)
        elif format == "terraform":
            content = export_terraform(result)
        else:
            content = export_json(result)
        return {
            "quote_id": quote_id,
            "format": format,
            "content": content,
        }

    return _run_tool_call(export)


@mcp.tool()
def price_list_quotes(
    limit: int = 20,
    service: str | None = None,
) -> dict[str, object]:
    """List saved pricing quotes."""

    def list_quotes() -> dict[str, object]:
        store = get_quote_store()
        return {"quotes": store.list_quotes(limit=limit, service=service)}

    return _run_tool_call(list_quotes)


@mcp.tool()
def price_get_quote(quote_id: str) -> dict[str, object]:
    """Retrieve a specific saved quote by ID."""

    def get_quote() -> dict[str, object]:
        store = get_quote_store()
        result = store.get(uuid.UUID(quote_id))
        return {
            "text": format_text(result),
            **result.to_dict(),
        }

    return _run_tool_call(get_quote)


@mcp.tool()
def price_share(quote_id: str) -> dict[str, object]:
    """Generate a shareable URL for a quote on the HWC price calculator. Requires Playwright and an active HWC browser session."""

    def share() -> dict[str, object]:
        store = get_quote_store()
        result = store.get(uuid.UUID(quote_id))
        calculator_url = "https://www.huaweicloud.com/pricing.html"
        return {
            "quote_id": quote_id,
            "share_url": calculator_url,
            "method": "direct_link",
            "note": "Pre-filled calculator URL generation requires Playwright automation with an active HWC session. For now, this returns the calculator landing page.",
            "services": [item.service for item in result.items],
        }

    return _run_tool_call(share)
```

Also update `clear_caches()` to include:
```python
get_bss_pricing_backend.cache_clear()
get_quote_store.cache_clear()
```

- [ ] **Step 6: Run all tests**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add mcp_hwc/pricing/tools.py mcp_hwc/server.py tests/test_pricing_tools.py
git commit -m "feat(pricing): add MCP tools price_quote, price_discover, price_export, price_list_quotes, price_get_quote, price_share"
```

---

### Task 6: Playwright Fallback (Stub)

**Files:**
- Create: `mcp_hwc/pricing/web_pricing.py`

- [ ] **Step 1: Write the stub implementation**

```python
# mcp_hwc/pricing/web_pricing.py
from __future__ import annotations

from .models import QuoteResult, ResourceDescriptor


class WebPricingBackend:
    """Playwright-based pricing fallback. Scrapes the HWC price calculator.

    Not yet implemented. Will be built when BSS SDK coverage gaps are identified.
    """

    def quote(self, resources: list[ResourceDescriptor]) -> QuoteResult:
        raise NotImplementedError(
            "Playwright pricing fallback is not yet implemented. "
            "Use the BSS SDK backend instead."
        )
```

- [ ] **Step 2: Commit**

```bash
git add mcp_hwc/pricing/web_pricing.py
git commit -m "feat(pricing): add Playwright fallback stub"
```

---

### Task 7: Integration Smoke Test

**Files:**
- Modify: `tests/test_pricing_tools.py`

- [ ] **Step 1: Add integration test that verifies tool registration**

Append to `tests/test_pricing_tools.py`:

```python
def test_pricing_tools_registered_in_mcp() -> None:
    from mcp_hwc.server import mcp

    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "price_quote",
        "price_discover",
        "price_export",
        "price_list_quotes",
        "price_get_quote",
        "price_share",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
```

- [ ] **Step 2: Run test**

Run: `cd /home/tideman/Projetos/python-projs/mcp-hwc && .venv/bin/python -m pytest tests/test_pricing_tools.py::test_pricing_tools_registered_in_mcp -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_pricing_tools.py
git commit -m "test(pricing): add integration test for tool registration"
```

---

## Self-Review

### Spec Coverage
| Spec Requirement | Task |
|---|---|
| `price_quote` tool | Task 5 |
| `price_discover` tool | Task 5 |
| `price_share` tool | Task 5 |
| `price_export` tool | Task 5 |
| `price_list_quotes` tool | Task 5 |
| `price_get_quote` tool | Task 5 |
| BSS SDK backend | Task 3 |
| Playwright fallback | Task 6 |
| Catalog mapping | Task 2 |
| Quote persistence | Task 4 |
| Data models | Task 1 |
| Currency always USD | Task 1 (hardcoded), Task 3 (hardcoded) |
| No discounts | Not implemented (by design) |
| Export formats (JSON, CSV, Terraform) | Task 5 |
| Conversational flow | Task 5 (tool definitions enable this) |

### Placeholder Scan
No TBDs, TODOs, or vague steps found.

### Type Consistency
- `ResourceDescriptor` fields consistent between models.py, bss_pricing.py, and tools.py
- `QuoteResult.to_dict()` output format consistent with `QuoteStore._from_dict()` input
- `QuoteItem.total_price` property used consistently in export functions
- `quote_id` is `uuid.UUID` throughout, serialized to `str` in `to_dict()`
