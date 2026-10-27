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


REAL = "https://www.thegoodguys.com.au/"


# Real pages fetched 2026-10-27 (trimmed to the JSON-LD and the price section).
def test_real_normal_price():
    raw = parse_product(load("goodguys_real_normal.html"), REAL + "bosch-series-4-flat-door-freestanding-dishwasher-brushed-steel-smp4hvi01a")
    n = normalize_offer(raw)
    assert (raw.retailer, raw.retailer_sku) == ("goodguys", "50099666")
    assert n.price.item_price == Decimal("899.00") and n.price.original_price is None
    assert n.stock == StockStatus.IN_STOCK
    assert raw.brand == "Bosch" and raw.gtin and raw.mpn  # model number used as MPN


def test_real_sale_price_from_strikethrough_ticket():
    raw = parse_product(load("goodguys_real_sale.html"), REAL + "acer-aspire-lite-14-14-inches-ryzen-3-8gb-256gb-laptop-nxdpfsa001")
    n = normalize_offer(raw)
    assert raw.retailer_sku == "50098090" and raw.title == 'Acer Aspire Lite 14 14" Ryzen 3 8GB 256GB Laptop'
    assert n.price.item_price == Decimal("639.00") and n.price.original_price == Decimal("799.00")
    assert n.price.retailer_discount_pct == Decimal("20.03")
    assert n.stock == StockStatus.IN_STOCK
    assert (raw.brand, raw.mpn, raw.gtin) == ("Acer", "NX.DPFSA.001", "4711474892812")


def test_real_coming_soon_is_not_removed():
    # The real page has a Product node with no offers; the old parser called it PRODUCT_REMOVED.
    raw = parse_product(load("goodguys_real_coming_soon.html"), REAL + "ring-spotlight-cam-2k-battery-2nd-gen-black-b0fwdwtnb9")
    n = normalize_offer(raw)
    assert raw.retailer_sku == "50099726"
    assert n.price.item_price == Decimal("279") and n.price.original_price is None
    assert n.stock == StockStatus.OUT_OF_STOCK


def test_real_agency_product_without_availability():
    n = normalize_offer(parse_product(load("goodguys_real_agency_no_availability.html"),
                                      REAL + "fisher-and-paykel-series-9-76cm-warming-drawer-grey-glass-wb76smg3"))
    assert n.retailer_sku == "50099078" and n.price.item_price == Decimal("2999.00")
    assert n.stock == StockStatus.UNKNOWN


def test_sku_falls_back_to_url_even_with_query_string():
    html = """<script type="application/ld+json">{"@type": "Product", "name": "N", "offers": {"price": "5"}}</script>"""
    raw = parse_product(html, URL + "?utm_source=x")
    assert raw.retailer_sku == "sony-wh-1000xm6-wireless-noise-cancelling-headphones-black"


# No real out-of-stock Good Guys page was found on 2026-10-27; this one stays synthetic.
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
    assert (await adapter_with(200, load("goodguys_real_sale.html")).fetch_product(URL)).price == "639.00"
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
