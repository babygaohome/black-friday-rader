from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealradar.models.enums import StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.retailers.base import ScanError, ScanErrorType
from dealradar.retailers.registry import RetailerRegistry
from retailers.harvey_norman.adapter import HarveyNormanAdapter
from retailers.harvey_norman.parser import parse_product

FIX = Path(__file__).parent.parent / "fixtures"
URL = "https://www.harveynorman.com.au/apple-macbook-air-13-inch-m4-16gb-512gb.html"


def load(name):
    return (FIX / name).read_text()


REAL = "https://www.harveynorman.com.au/"


# Real pages fetched 2026-10-27 (trimmed to the JSON-LD and the price card).
def test_real_normal_price():
    raw = parse_product(load("harvey_norman_real_normal.html"), REAL + "caroma-urbane-ii-compact-twin-shower-chrome.html")
    n = normalize_offer(raw)
    assert (raw.retailer, raw.retailer_sku) == ("harveynorman", "99632C3A")
    assert n.price.item_price == Decimal("438") and n.price.original_price is None
    assert n.stock == StockStatus.IN_STOCK
    assert (raw.brand, raw.gtin) == ("Caroma", "9312547933859")


def test_real_out_of_stock():
    # The page shows "Coming Soon / Pre-Order Available from 29th October"; JSON-LD says OutOfStock.
    raw = parse_product(load("harvey_norman_real_out_of_stock.html"), REAL + "apple-ipad-mini-wi-fi-128gb-with-standard-glass-midnight.html")
    n = normalize_offer(raw)
    assert raw.retailer_sku == "6905727" and n.title == "Apple iPad mini Wi‑Fi 128GB with standard glass - Midnight"
    assert n.price.item_price == Decimal("1099") and n.stock == StockStatus.OUT_OF_STOCK
    assert (raw.brand, raw.gtin) == ("Apple", "195951205458")


def test_real_preorder():
    url = REAL + "asus-proart-p14-14-inch-nvidia-rtx-spark-n1x-20-core-32gb-1tb-ssd-3k-120hz-oled-touchscreen-laptop-neo-white.html"
    n = normalize_offer(parse_product(load("harvey_norman_real_preorder.html"), url))
    assert n.retailer_sku == "H7407BA-SU300W" and n.price.item_price == Decimal("6499")
    assert n.stock == StockStatus.PREORDER


def test_sku_falls_back_to_url_even_with_query_string():
    html = """<script type="application/ld+json">{"@type": "Product", "name": "N", "offers": {"price": "5"}}</script>"""
    raw = parse_product(html, URL + "?utm_source=x")
    assert raw.retailer_sku == "apple-macbook-air-13-inch-m4-16gb-512gb"


# Harvey Norman product pages expose only the current price (no was/RRP) in static HTML,
# and no discounted real page was found on 2026-10-27; this sale sample stays synthetic.
def test_sale_price():
    n = normalize_offer(parse_product(load("harvey_norman_sale.html"), URL))
    assert n.price.item_price == Decimal("399.00") and n.price.original_price == Decimal("549.00")
    assert n.price.retailer_discount_pct == Decimal("27.32")


@pytest.mark.parametrize("fixture,error", [
    ("harvey_norman_no_offer.html", ScanErrorType.PRODUCT_REMOVED),
    ("harvey_norman_no_jsonld.html", ScanErrorType.PARSE_ERROR),
    ("harvey_norman_challenge.html", ScanErrorType.CAPTCHA),
])
def test_parse_errors(fixture, error):
    with pytest.raises(ScanError) as exc:
        parse_product(load(fixture), URL)
    assert exc.value.error_type == error


def adapter_with(status, body=""):
    async def fetcher(url):
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))
    return HarveyNormanAdapter(fetcher=fetcher)


async def test_adapter_fetch_ok_and_http_errors():
    assert (await adapter_with(200, load("harvey_norman_sale.html")).fetch_product(URL)).price == "399.00"
    for status, error in [(429, ScanErrorType.RATE_LIMIT), (403, ScanErrorType.CAPTCHA), (404, ScanErrorType.PRODUCT_REMOVED),
                          (302, ScanErrorType.UNKNOWN), (503, ScanErrorType.NETWORK_ERROR)]:
        with pytest.raises(ScanError) as exc:
            await adapter_with(status).fetch_product(URL)
        assert exc.value.error_type == error


async def test_adapter_network_error_and_foreign_url():
    async def boom(url):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(ScanError) as exc:
        await HarveyNormanAdapter(fetcher=boom).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.NETWORK_ERROR
    with pytest.raises(ScanError):
        await adapter_with(200, "x").fetch_product("https://evil.com/p/x")


def test_registered_in_default_registry():
    from dealradar.retailers.builtin import build_default_registry

    assert "harveynorman" in build_default_registry().codes()


def test_registry_integration_and_domain_lookalikes():
    reg = RetailerRegistry()
    reg.register(HarveyNormanAdapter())
    assert reg.resolve(URL).code == "harveynorman"
    for bad in ["https://harveynorman.com.au.evil.com/p", "https://evilharveynorman.com.au/p", "http://www.harveynorman.com.au/p"]:
        with pytest.raises(Exception):
            reg.resolve(bad)
