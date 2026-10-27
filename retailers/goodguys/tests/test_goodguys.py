from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealradar.models.enums import StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.retailers.base import ScanError, ScanErrorType
from dealradar.retailers.registry import RetailerRegistry
from retailers.goodguys.adapter import GoodGuysAdapter
from retailers.goodguys.parser import parse_product

FIX = Path(__file__).parent.parent / "fixtures"
URL = "https://www.thegoodguys.com.au/sony-wh-1000xm6-wireless-noise-cancelling-headphones-black"


def load(name):
    return (FIX / name).read_text()


def test_normal_price():
    raw = parse_product(load("goodguys_product_normal.html"), URL)
    n = normalize_offer(raw)
    assert raw.retailer == "goodguys" and raw.retailer_sku == "SONWH1000XM6B"
    assert n.price.item_price == Decimal("549.00") and n.price.original_price is None
    assert n.stock == StockStatus.IN_STOCK
    assert (raw.brand, raw.mpn, raw.gtin) == ("Sony", "WH1000XM6B", "4548736145871")


def test_sku_falls_back_to_url_even_with_query_string():
    html = """<script type="application/ld+json">{"@type": "Product", "name": "N", "offers": {"price": "5"}}</script>"""
    raw = parse_product(html, URL + "?utm_source=x")
    assert raw.retailer_sku == "sony-wh-1000xm6-wireless-noise-cancelling-headphones-black"


def test_sale_price():
    n = normalize_offer(parse_product(load("goodguys_sale.html"), URL))
    assert n.price.item_price == Decimal("399.00") and n.price.original_price == Decimal("549.00")
    assert n.price.retailer_discount_pct == Decimal("27.32")


def test_out_of_stock():
    assert normalize_offer(parse_product(load("goodguys_out_of_stock.html"), URL)).stock == StockStatus.OUT_OF_STOCK


@pytest.mark.parametrize("fixture,error", [
    ("goodguys_no_offer.html", ScanErrorType.PRODUCT_REMOVED),
    ("goodguys_no_jsonld.html", ScanErrorType.PARSE_ERROR),
    ("goodguys_challenge.html", ScanErrorType.CAPTCHA),
])
def test_parse_errors(fixture, error):
    with pytest.raises(ScanError) as exc:
        parse_product(load(fixture), URL)
    assert exc.value.error_type == error


def adapter_with(status, body=""):
    async def fetcher(url):
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))
    return GoodGuysAdapter(fetcher=fetcher)


async def test_adapter_fetch_ok_and_http_errors():
    assert (await adapter_with(200, load("goodguys_sale.html")).fetch_product(URL)).price == "399.00"
    for status, error in [(429, ScanErrorType.RATE_LIMIT), (403, ScanErrorType.CAPTCHA), (404, ScanErrorType.PRODUCT_REMOVED),
                          (302, ScanErrorType.UNKNOWN), (503, ScanErrorType.NETWORK_ERROR)]:
        with pytest.raises(ScanError) as exc:
            await adapter_with(status).fetch_product(URL)
        assert exc.value.error_type == error


async def test_adapter_network_error_and_foreign_url():
    async def boom(url):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(ScanError) as exc:
        await GoodGuysAdapter(fetcher=boom).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.NETWORK_ERROR
    with pytest.raises(ScanError):
        await adapter_with(200, "x").fetch_product("https://evil.com/p/x")


def test_registered_in_default_registry():
    from dealradar.retailers.builtin import build_default_registry

    assert "goodguys" in build_default_registry().codes()


def test_registry_integration_and_domain_lookalikes():
    reg = RetailerRegistry()
    reg.register(GoodGuysAdapter())
    assert reg.resolve(URL).code == "goodguys"
    for bad in ["https://thegoodguys.com.au.evil.com/p", "https://evilthegoodguys.com.au/p", "http://www.thegoodguys.com.au/p"]:
        with pytest.raises(Exception):
            reg.resolve(bad)
