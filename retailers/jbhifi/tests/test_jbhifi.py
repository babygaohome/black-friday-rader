from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealradar.models.enums import StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.retailers.base import ScanError, ScanErrorType
from dealradar.retailers.registry import RetailerRegistry
from retailers.jbhifi.adapter import JBHiFiAdapter
from retailers.jbhifi.parser import parse_product

FIX = Path(__file__).parent.parent / "fixtures"
URL = "https://www.jbhifi.com.au/products/sony-wh1000xm6"


def load(name):
    return (FIX / name).read_text()


def test_normal_price():
    raw = parse_product(load("jbhifi_product_normal.html"), URL)
    n = normalize_offer(raw)
    assert raw.retailer == "jbhifi" and raw.retailer_sku == "123456"
    assert n.price.item_price == Decimal("549.00") and n.price.original_price is None
    assert n.stock == StockStatus.IN_STOCK
    assert (raw.brand, raw.mpn, raw.gtin) == ("Sony", "WH1000XM6B", "4548736145871")


def test_real_normal_price():
    # Real page fetched 2026-10-27 (200 this time; an earlier product URL got the 429 challenge).
    url = "https://www.jbhifi.com.au/products/lenovo-15iph12-15-3-2-8k-oled-touch-googlebook-intel-core-ultra-5-325256gb"
    raw = parse_product(load("jbhifi_real_normal.html"), url)
    n = normalize_offer(raw)
    assert (raw.retailer_sku, raw.brand, raw.gtin) == ("915278", "LENOVO", "828132231358")
    assert raw.title.startswith("Lenovo 15IPH12")
    # JB lists a ListPrice equal to the current price; that must not count as a discount.
    assert n.price.item_price == Decimal("2199.00") and n.price.original_price is None
    assert n.stock == StockStatus.IN_STOCK


def test_real_sale_price():
    # Real page fetched 2026-10-27: ListPrice 699 + SalePrice 499 in priceSpecification.
    url = "https://www.jbhifi.com.au/products/lg-ultragear-g6-27g64na-27-qhd-300hz-gaming-monitor"
    raw = parse_product(load("jbhifi_real_sale.html"), url)
    n = normalize_offer(raw)
    assert raw.retailer_sku == "899041"
    assert n.price.item_price == Decimal("499.00") and n.price.original_price == Decimal("699.00")
    assert n.price.retailer_discount_pct == Decimal("28.61")
    assert n.stock == StockStatus.IN_STOCK


def test_real_preorder():
    # Real page fetched 2026-10-27: not yet released, JSON-LD availability PreOrder.
    n = normalize_offer(parse_product(load("jbhifi_real_preorder.html"), "https://www.jbhifi.com.au/products/apple-homeview-space-grey"))
    assert n.retailer_sku == "915022" and n.price.item_price == Decimal("449.00") and n.price.original_price is None
    assert n.stock == StockStatus.PREORDER


def test_sale_price():
    # Synthetic pair to jbhifi_product_normal.html; scanner/alert tests elsewhere rely on the 549 -> 399 drop.
    n = normalize_offer(parse_product(load("jbhifi_sale.html"), URL))
    assert n.price.item_price == Decimal("399.00")
    assert n.price.original_price == Decimal("549.00")
    assert n.price.retailer_discount_pct == Decimal("27.32")


def test_out_of_stock():
    n = normalize_offer(parse_product(load("jbhifi_out_of_stock.html"), URL))
    assert n.stock == StockStatus.OUT_OF_STOCK


@pytest.mark.parametrize("fixture,error", [
    ("jbhifi_no_offer.html", ScanErrorType.PRODUCT_REMOVED),
    ("jbhifi_no_jsonld.html", ScanErrorType.PARSE_ERROR),
    ("jbhifi_challenge.html", ScanErrorType.CAPTCHA),
])
def test_parse_errors(fixture, error):
    with pytest.raises(ScanError) as exc:
        parse_product(load(fixture), URL)
    assert exc.value.error_type == error


def test_real_challenge_page_is_captcha():
    with pytest.raises(ScanError) as exc:
        parse_product(load("jbhifi_real_challenge_429.html"), URL)
    assert exc.value.error_type == ScanErrorType.CAPTCHA


async def test_real_429_challenge_response_is_captcha_not_rate_limit():
    # What JB Hi-Fi actually returned to our scanner on 2026-10-27.
    with pytest.raises(ScanError) as exc:
        await adapter_with(429, load("jbhifi_real_challenge_429.html")).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.CAPTCHA


def adapter_with(status, body=""):
    async def fetcher(url):
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))
    return JBHiFiAdapter(fetcher=fetcher)


async def test_adapter_fetch_ok():
    raw = await adapter_with(200, load("jbhifi_sale.html")).fetch_product(URL)
    assert raw.price == "399.00"


@pytest.mark.parametrize("status,error", [
    (429, ScanErrorType.RATE_LIMIT),
    (403, ScanErrorType.CAPTCHA),
    (404, ScanErrorType.PRODUCT_REMOVED),
    (302, ScanErrorType.UNKNOWN),
    (503, ScanErrorType.NETWORK_ERROR),
])
async def test_adapter_http_errors(status, error):
    with pytest.raises(ScanError) as exc:
        await adapter_with(status).fetch_product(URL)
    assert exc.value.error_type == error


async def test_adapter_network_error_and_foreign_url():
    async def boom(url):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(ScanError) as exc:
        await JBHiFiAdapter(fetcher=boom).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.NETWORK_ERROR
    with pytest.raises(ScanError):
        await adapter_with(200, "x").fetch_product("https://evil.com/products/x")


def test_registry_integration():
    reg = RetailerRegistry()
    reg.register(JBHiFiAdapter())
    assert reg.resolve(URL).code == "jbhifi"
