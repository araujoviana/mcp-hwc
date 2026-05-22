from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from .catalog import CLOUD_SERVICE_TYPES
from .models import QuoteItem, QuoteResult, ResourceDescriptor

log = logging.getLogger(__name__)

CALCULATOR_BASE = "https://www.huaweicloud.com/intl/en-us/pricing/calculator.html"

SERVICE_HASH_MAP: dict[str, str] = {
    "ecs": "ecs",
    "evs": "evs",
    "vpc": "vpc",
    "eip": "eip",
    "elb": "elb",
    "nat": "nat",
    "rds": "rds",
    "dds": "dds",
    "dcs": "dcs",
    "dms": "dms",
    "obs": "obs",
    "sfs": "sfs",
    "cce": "cce",
    "functiongraph": "functiongraph",
    "kms": "kms",
    "smn": "smn",
    "ces": "ces",
    "dns": "dns",
    "waf": "waf",
    "cdn": "cdn",
}


class WebPricingBackend:
    """Playwright-based pricing fallback. Scrapes the HWC price calculator."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless

    async def quote(self, resources: list[ResourceDescriptor]) -> QuoteResult:
        from playwright.async_api import async_playwright

        items: list[QuoteItem] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self._headless)
            for desc in resources:
                try:
                    item = await self._quote_single(browser, desc)
                    if item is not None:
                        items.append(item)
                except Exception as exc:
                    log.warning("Web pricing failed for %s/%s: %s", desc.service, desc.spec, exc)
            await browser.close()

        if not items:
            raise RuntimeError(
                "Web pricing could not price any resources. "
                "The HWC calculator may have changed its structure."
            )
        return QuoteResult(
            quote_id=uuid.uuid4(),
            items=tuple(items),
            currency="USD",
            created_at=datetime.now(timezone.utc),
        )

    async def _quote_single(self, browser, desc: ResourceDescriptor) -> QuoteItem | None:
        page = await browser.new_page()
        try:
            return await self._scrape_calculator(page, desc)
        finally:
            await page.close()

    async def _scrape_calculator(self, page, desc: ResourceDescriptor) -> QuoteItem | None:
        service_hash = SERVICE_HASH_MAP.get(desc.service)
        if service_hash is None:
            log.warning("No calculator route for service '%s'", desc.service)
            return None

        url = f"{CALCULATOR_BASE}#/{service_hash}"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        await self._dismiss_dialogs(page)
        await self._select_region(page, desc.region)
        await self._select_billing_mode(page, desc.period_type)
        await self._select_spec(page, desc.spec)
        await page.wait_for_timeout(2000)

        price = await self._read_price(page)
        if price is None:
            log.warning("Could not read price for %s/%s", desc.service, desc.spec)
            return None

        return QuoteItem(
            service=desc.service,
            spec=desc.spec,
            region=desc.region,
            period_type=desc.period_type,
            period_num=desc.period_num,
            quantity=desc.quantity,
            unit_price=price,
            currency="USD",
        )

    @staticmethod
    async def _dismiss_dialogs(page) -> None:
        for selector in [
            ".tiny-dialog-box__close",
            ".guide-dialog .close",
            "button:has-text('Do not show')",
            ".func-guide-close",
        ]:
            try:
                close_btn = await page.query_selector(selector)
                if close_btn:
                    await close_btn.click(force=True)
                    await page.wait_for_timeout(300)
            except Exception:
                pass

    @staticmethod
    async def _select_region(page, region: str) -> None:
        region_label = _region_label(region)
        try:
            region_trigger = await page.query_selector(
                ".func-region-select, "
                "[class*='region'] .func-select-input, "
                ".calculator-region select"
            )
            if region_trigger:
                await region_trigger.click()
                await page.wait_for_timeout(500)
                option = await page.query_selector(f"text={region_label}")
                if option:
                    await option.click()
                    await page.wait_for_timeout(500)
                    return
        except Exception as exc:
            log.debug("Region selector approach 1 failed: %s", exc)

        try:
            inputs = await page.query_selector_all(
                "input[placeholder='Select'], "
                "input[placeholder*='Region']"
            )
            for inp in inputs:
                await inp.click()
                await page.wait_for_timeout(500)
                option = await page.query_selector(f"text={region_label}")
                if option:
                    await option.click()
                    await page.wait_for_timeout(500)
                    return
                await inp.press("Escape")
        except Exception as exc:
            log.debug("Region selector approach 2 failed: %s", exc)

    @staticmethod
    async def _select_billing_mode(page, period_type: str) -> None:
        if period_type == "on_demand":
            label = "Pay-per-use"
        elif period_type == "year":
            label = "Yearly/Monthly"
        else:
            label = "Yearly/Monthly"

        try:
            billing_radio = await page.query_selector(f"text={label}")
            if billing_radio:
                await billing_radio.click(force=True)
                await page.wait_for_timeout(500)
        except Exception as exc:
            log.debug("Billing mode selection failed: %s", exc)

    @staticmethod
    async def _select_spec(page, spec: str) -> None:
        try:
            spec_input = await page.query_selector(
                "input[placeholder*='spec'], "
                "input[placeholder*='flavor']"
            )
            if spec_input:
                await spec_input.fill(spec)
                await spec_input.press("Enter")
                await page.wait_for_timeout(500)
                return

            spec_link = await page.query_selector(f"text={spec}")
            if spec_link:
                await spec_link.click()
                await page.wait_for_timeout(500)
        except Exception as exc:
            log.debug("Spec selection failed: %s", exc)

    @staticmethod
    async def _read_price(page) -> float | None:
        price_selectors = [
            ".func-priceboard-priceinfo",
            ".func-priceboard-sub-priceinfo",
            ".func-priceboard-leftinfo",
            "[class*='priceboard']",
        ]
        for selector in price_selectors:
            try:
                el = await page.query_selector(selector)
                if el:
                    text = (await el.inner_text() or "").strip()
                    price = _extract_price(text)
                    if price is not None:
                        return price
            except Exception:
                continue
        return None


def _region_label(region: str) -> str:
    _LABELS = {
        "sa-brazil-1": "LA-Sao Paulo",
        "la-north-2": "LA-Mexico City",
        "na-mexico-1": "LA-Mexico City",
        "ap-southeast-1": "AP-Hong Kong",
        "ap-southeast-2": "AP-Bangkok",
        "ap-southeast-3": "AP-Singapore",
        "af-south-1": "AF-Johannesburg",
        "af-north-1": "AF-Cairo",
        "tr-west-1": "TR-Istanbul",
        "cn-north-1": "CN Beijing1",
        "cn-north-4": "CN North-4",
        "cn-east-3": "CN East-3",
        "cn-south-1": "CN South-1",
        "cn-southwest-2": "CN Southwest-2",
    }
    return _LABELS.get(region, region)


def _extract_price(text: str) -> float | None:
    import re

    match = re.search(r"USD\s*([\d,]+\.?\d*)", text)
    if match:
        return float(match.group(1).replace(",", ""))
    match = re.search(r"\$\s*([\d,]+\.?\d*)", text)
    if match:
        return float(match.group(1).replace(",", ""))
    match = re.search(r"([\d,]+\.\d{2})", text)
    if match:
        return float(match.group(1).replace(",", ""))
    return None
