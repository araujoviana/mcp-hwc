from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Literal

from mcp.server.fastmcp.exceptions import ToolError

from mcp_hwc.pricing.bss_pricing import BssAccessDenied, PricingNotAvailable
from mcp_hwc.pricing.catalog import CLOUD_SERVICE_TYPES
from mcp_hwc.pricing.models import ResourceDescriptor
from mcp_hwc.pricing.tools import export_csv, export_json, export_terraform, format_text
from mcp_hwc.server import (
    _run_tool_call,
    get_bss_pricing_backend,
    get_quote_store,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


async def price_quote(
    action: Literal["create", "get", "list", "export", "share"] = "create",
    resources: list[dict[str, object]] | None = None,
    region: str | None = None,
    quote_id: str | None = None,
    format: str = "json",
    limit: int = 20,
    service: str | None = None,
) -> dict[str, object]:
    """Create, retrieve, list, export, or share a Huawei Cloud pricing quote.

    action='create' (default): requires resources (list of dicts, each needing service, spec,
    region, period_type; optional period_num, quantity, size).
    action='get': requires quote_id. Retrieves a previously saved quote.
    action='list': optional limit/service filter. Lists saved quotes.
    action='export': requires quote_id; format is 'json' (default), 'csv', or 'terraform'.
    action='share': requires quote_id. Returns a shareable calculator URL.
    """

    if action == "create":
        if not resources:
            raise ToolError("resources is required for action='create'")

        descs = []
        for r in resources:
            r_region = str(r.get("region", "") or region or "")
            if not r_region:
                raise ToolError("region is required (per-resource or top-level)")

            size = r.get("size")
            if size is not None:
                size = float(size)

            descs.append(
                ResourceDescriptor(
                    service=str(r["service"]),
                    spec=str(r["spec"]),
                    region=r_region,
                    period_type=str(r["period_type"]),
                    period_num=int(r.get("period_num", 1)),
                    quantity=int(r.get("quantity", 1)),
                    size=size,
                )
            )

        backend = get_bss_pricing_backend()
        try:
            result = await asyncio.to_thread(backend.quote, descs)
        except BssAccessDenied as exc:
            raise ToolError(f"BSS pricing API access denied (CBC.0156): {exc}") from exc
        except PricingNotAvailable as exc:
            raise ToolError(f"BSS pricing API unavailable: {exc}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        get_quote_store().save(result)
        return {
            "text": format_text(result),
            **result.to_dict(),
        }

    if action == "list":
        def list_quotes() -> dict[str, object]:
            store = get_quote_store()
            return {"quotes": store.list_quotes(limit=limit, service=service)}

        return _run_tool_call(list_quotes)

    if not quote_id:
        raise ToolError(f"quote_id is required for action='{action}'")

    if action == "get":
        def get_quote() -> dict[str, object]:
            store = get_quote_store()
            result = store.get(uuid.UUID(quote_id))
            return {
                "text": format_text(result),
                **result.to_dict(),
            }

        return _run_tool_call(get_quote)

    if action == "export":
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

    if action == "share":
        def share() -> dict[str, object]:
            store = get_quote_store()
            result = store.get(uuid.UUID(quote_id))
            services = [item.service for item in result.items]
            primary_service = services[0] if services else None

            if primary_service and primary_service in CLOUD_SERVICE_TYPES:
                calculator_url = (
                    f"https://www.huaweicloud.com/intl/en-us/pricing/calculator.html#/{primary_service}"
                )
                method = "calculator_service_page"
            else:
                calculator_url = "https://www.huaweicloud.com/intl/en-us/pricing.html"
                method = "calculator_landing_page"

            return {
                "quote_id": quote_id,
                "share_url": calculator_url,
                "method": method,
                "services": services,
                "note": (
                    "The URL navigates to the calculator section for the primary service. "
                    "Quote parameters must be re-entered in the calculator."
                ),
            }

        return _run_tool_call(share)

    raise ToolError(f"Unsupported action '{action}'")


def _catalog_fallback_specs(
    service: str,
    keyword: str | None = None,
) -> list[dict[str, str]]:
    from mcp_hwc.pricing.catalog import RESOURCE_TYPES

    key = service.strip().lower()
    if key not in CLOUD_SERVICE_TYPES:
        return []
    entry = {
        "resource_type": RESOURCE_TYPES.get(key, ""),
        "resource_spec": "",
        "resource_spec_desc": f"Service '{service}' is known but spec discovery requires BSS API access.",
    }
    if keyword and keyword.lower() not in entry["resource_spec_desc"].lower():
        return []
    return [entry]


async def price_discover(
    service: str,
    region: str | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    """Discover available resource types and specs for a Huawei Cloud service."""

    backend = get_bss_pricing_backend()
    try:
        specs = await asyncio.to_thread(
            backend.discover_specs, service, region=region, keyword=keyword
        )
    except BssAccessDenied:
        specs = _catalog_fallback_specs(service, keyword=keyword)
        if not specs:
            raise ToolError(
                f"BSS API access denied (CBC.0156). Cannot discover specs for '{service}'. "
                f"Known services: {', '.join(sorted(CLOUD_SERVICE_TYPES.keys()))}"
            )
        return {
            "service": service,
            "region": region,
            "specs": specs,
            "count": len(specs),
            "source": "catalog_fallback",
        }
    except PricingNotAvailable:
        raise ToolError(
            f"Pricing not available for '{service}'. "
            f"Known services: {', '.join(sorted(CLOUD_SERVICE_TYPES.keys()))}"
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "service": service,
        "region": region,
        "specs": specs,
        "count": len(specs),
    }


def register_pricing_tools(mcp: FastMCP):
    mcp.tool()(price_quote)
    mcp.tool()(price_discover)
