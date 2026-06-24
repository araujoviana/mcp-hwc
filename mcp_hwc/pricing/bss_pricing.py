from __future__ import annotations

import logging
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

from mcp_hwc.pricing.catalog import DEMAND_MEASURE_IDS, resolve_cloud_service_type, resolve_region, resolve_resource_type
from mcp_hwc.pricing.models import QuoteItem, QuoteResult, ResourceDescriptor

if TYPE_CHECKING:
    from mcp_hwc.core.config import CloudApiConfig

log = logging.getLogger(__name__)


class PricingNotAvailable(RuntimeError):
    """Exception raised when the BSS SDK is unable to retrieve pricing information."""


class BssAccessDenied(PricingNotAvailable):
    """Exception raised when the BSS API returns a 403 Forbidden error, indicating insufficient permissions."""


class BssPricingBackend:
    def __init__(self, config: CloudApiConfig) -> None:
        self._config = config
        self._client: BssClient | None = None

    def _get_client(self) -> BssClient:
        if self._client is not None:
            return self._client
        self._client = self._build_client()
        return self._client

    def _build_client(self) -> BssClient:
        from huaweicloudsdkcore.auth.credentials import GlobalCredentials

        creds = GlobalCredentials(
            ak=self._config.access_key_id,
            sk=self._config.secret_access_key,
        )
        if self._config.security_token:
            creds.security_token = self._config.security_token
        if self._config.domain_id:
            creds.domain_id = self._config.domain_id

        region = self._config.region or "myhuaweicloud.com"
        endpoint = self._config.endpoint or "bss.myhuaweicloud.com"
        sdk_region = SdkRegion(id=region, endpoint=endpoint)

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

        response = self._call_api(self._get_client().list_rate_on_period_detail, request)

        official = response.official_website_rating_result
        if official is None or not official.product_rating_results:
            raise PricingNotAvailable("BSS subscription pricing returned no results")

        return self._resolve_quote_items(official.product_rating_results, resources)

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

        response = self._call_api(self._get_client().list_on_demand_resource_ratings, request)

        results = response.product_rating_results
        if not results:
            raise PricingNotAvailable("BSS on-demand pricing returned no results")

        return self._resolve_quote_items(results, resources, period_type_override="on_demand", period_num_override=1)

    @staticmethod
    def _resolve_quote_items(
        raw_results: list,
        resources: list[ResourceDescriptor],
        *,
        period_type_override: str | None = None,
        period_num_override: int | None = None,
    ) -> list[QuoteItem]:
        items: list[QuoteItem] = []
        for pos, result in enumerate(raw_results):
            try:
                idx = int(result.id) if result.id is not None else pos
            except ValueError:
                idx = pos
            if not (0 <= idx < len(resources)):
                continue
            desc = resources[idx]
            amount = float(result.official_website_amount or 0)
            items.append(
                QuoteItem(
                    service=desc.service,
                    spec=desc.spec,
                    region=desc.region,
                    period_type=period_type_override if period_type_override is not None else desc.period_type,
                    period_num=period_num_override if period_num_override is not None else desc.period_num,
                    quantity=desc.quantity,
                    size=desc.size,
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
        kwargs = {
            "id": str(index),
            "cloud_service_type": resolve_cloud_service_type(desc.service),
            "resource_type": resolve_resource_type(desc.service),
            "resource_spec": desc.spec,
            "region": resolve_region(desc.region),
            "period_type": BssPricingBackend._map_period_type(desc.period_type),
            "period_num": desc.period_num,
            "subscription_num": desc.quantity,
        }
        if desc.size is not None:
            kwargs["resource_size"] = int(desc.size)
            kwargs["size_measure_id"] = 17  # GB
        return PeriodProductInfo(**kwargs)

    @staticmethod
    def _build_demand_product_info(desc: ResourceDescriptor, index: int) -> DemandProductInfo:
        kwargs: dict[str, object] = {
            "id": str(index),
            "cloud_service_type": resolve_cloud_service_type(desc.service),
            "resource_type": resolve_resource_type(desc.service),
            "resource_spec": desc.spec,
            "region": resolve_region(desc.region),
            "subscription_num": desc.quantity,
        }
        if desc.size is not None:
            kwargs["resource_size"] = int(desc.size)
            kwargs["size_measure_id"] = 17  # GB
            kwargs["usage_value"] = float(desc.size)
            kwargs["usage_measure_id"] = DEMAND_MEASURE_IDS.get(desc.service.lower(), 17)
        else:
            kwargs["usage_value"] = 1.0
            kwargs["usage_measure_id"] = DEMAND_MEASURE_IDS.get(desc.service.lower(), 1)
        return DemandProductInfo(**kwargs)

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
        response = self._call_api(self._get_client().list_service_resources, request)

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

    @staticmethod
    def _call_api(fn, request):
        try:
            return fn(request)
        except Exception as exc:
            msg = str(exc)
            if "CBC.0156" in msg or "403" in msg:
                raise BssAccessDenied(
                    "BSS API access denied (CBC.0156). "
                    "The account may not have the BSS pricing API enabled."
                ) from exc
            raise PricingNotAvailable(f"BSS API error: {msg}") from exc
