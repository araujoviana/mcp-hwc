from __future__ import annotations
import uuid
from typing import TYPE_CHECKING
from mcp.server.fastmcp.exceptions import ToolError
from mcp_hwc.server import (
    _run_tool_call,
    get_bss_pricing_backend,
    get_quote_store,
)
from mcp_hwc.pricing.models import ResourceDescriptor
from mcp_hwc.pricing.bss_pricing import BssAccessDenied, PricingNotAvailable
from mcp_hwc.pricing.web_pricing import SERVICE_HASH_MAP
from mcp_hwc.pricing.tools import export_csv, export_json, export_terraform, format_text

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from mcp_hwc.pricing.models import QuoteResult

async def _web_fallback_quote(descs: list[ResourceDescriptor]) -> QuoteResult:
    from mcp_hwc.pricing.web_pricing import WebPricingBackend
    web = WebPricingBackend(headless=True)
    return await web.quote(descs)

async def price_quote(
    resources: list[dict[str, object]],
    region: str | None = None,
) -> dict[str, object]:
    """Get pricing/quotation for Huawei Cloud resources. Each resource dict needs: service, spec, region, period_type. Optional: period_num, quantity."""

    descs = []
    for r in resources:
        r_region = str(r.get("region", "") or region or "")
        if not r_region:
            raise ToolError("region is required (per-resource or top-level)")
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
    except BssAccessDenied:
        result = await _web_fallback_quote(descs)
    except PricingNotAvailable:
        result = await _web_fallback_quote(descs)

    get_quote_store().save(result)
    return {
        "text": format_text(result),
        **result.to_dict(),
    }

async def price_discover(
    service: str,
    region: str | None = None,
    keyword: str | None = None,
) -> dict[str, object]:
    """Discover available resource types and specs for a Huawei Cloud service."""

    backend = get_bss_pricing_backend()
    try:
        specs = backend.discover_specs(service, region=region, keyword=keyword)
    except BssAccessDenied:
        raise ToolError(
            f"BSS API access denied (CBC.0156). Cannot discover specs for '{service}'. "
            f"Known services: {', '.join(sorted(SERVICE_HASH_MAP.keys()))}"
        )
    except PricingNotAvailable:
        raise ToolError(
            f"Pricing not available for '{service}'. "
            f"Known services: {', '.join(sorted(SERVICE_HASH_MAP.keys()))}"
        )
    return {
        "service": service,
        "region": region,
        "specs": specs,
        "count": len(specs),
    }

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

def price_list_quotes(
    limit: int = 20,
    service: str | None = None,
) -> dict[str, object]:
    """List saved pricing quotes."""

    def list_quotes() -> dict[str, object]:
        store = get_quote_store()
        return {"quotes": store.list_quotes(limit=limit, service=service)}

    return _run_tool_call(list_quotes)

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

def register_pricing_tools(mcp: FastMCP):
    mcp.tool()(price_quote)
    mcp.tool()(price_discover)
    mcp.tool()(price_export)
    mcp.tool()(price_list_quotes)
    mcp.tool()(price_get_quote)
    mcp.tool()(price_share)
