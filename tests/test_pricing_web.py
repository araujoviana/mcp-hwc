from __future__ import annotations

from mcp_hwc.pricing.web_pricing import _extract_price, _region_label


def test_extract_price_usd() -> None:
    assert _extract_price("USD 89.11") == 89.11


def test_extract_price_dollar_sign() -> None:
    assert _extract_price("$ 123.45") == 123.45


def test_extract_price_bare_number() -> None:
    assert _extract_price("Total: 56.78 USD") == 56.78


def test_extract_price_with_comma() -> None:
    assert _extract_price("USD 1,234.56") == 1234.56


def test_extract_price_none() -> None:
    assert _extract_price("no price here") is None


def test_region_label_known() -> None:
    assert _region_label("sa-brazil-1") == "LA-Sao Paulo"


def test_region_label_unknown_passthrough() -> None:
    assert _region_label("ap-southeast-4") == "ap-southeast-4"
