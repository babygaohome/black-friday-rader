from decimal import Decimal

import pytest

from dealradar.models.enums import StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.normalization.price import build_breakdown, parse_money
from dealradar.normalization.stock import normalize_stock
from dealradar.normalization.validation import validate_price
from dealradar.retailers.base import RawOffer, RetailerAdapter, ScanError, ScanErrorType, UnsupportedUrl
from dealradar.retailers.registry import RetailerRegistry


class FakeAdapter(RetailerAdapter):
    code = "jbhifi"
    name = "JB Hi-Fi"
    domains = ("jbhifi.com.au",)

    async def fetch_product(self, url):
        return RawOffer("jbhifi", "1", "t", url, "10")


@pytest.mark.parametrize("raw,expected", [
    ("Available now", StockStatus.IN_STOCK),
    ("Online only", StockStatus.IN_STOCK),
    ("In stock", StockStatus.IN_STOCK),
    ("Ready to ship", StockStatus.IN_STOCK),
    ("https://schema.org/InStock", StockStatus.IN_STOCK),
    ("https://schema.org/OutOfStock", StockStatus.OUT_OF_STOCK),
    ("Currently unavailable", StockStatus.OUT_OF_STOCK),
    ("Pre-order", StockStatus.PREORDER),
    ("https://schema.org/PreOrder", StockStatus.PREORDER),
    ("Backordered", StockStatus.BACKORDER),
    ("Only 3 left", StockStatus.LOW_STOCK),
    ("Limited stock", StockStatus.LOW_STOCK),
    ("whatever", StockStatus.UNKNOWN),
    ("", StockStatus.UNKNOWN),
    (None, StockStatus.UNKNOWN),
])
def test_stock_mapping(raw, expected):
    assert normalize_stock(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("$1,299.00", "1299.00"), ("A$399", "399.00"), (399, "399.00"), (399.5, "399.50"),
    ("399,50", "399.50"), ("1,299", "1299.00"),
    (None, None), ("free", None), ("", None),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == (Decimal(expected) if expected else None)


def test_effective_price_with_coupon_and_shipping():
    b = build_breakdown("449", original_price="549", coupon="50", shipping="0")
    assert b.effective_price == Decimal("399.00")
    assert b.retailer_discount_pct == Decimal("18.21")
    assert build_breakdown("100", shipping="9.95").effective_price == Decimal("109.95")
    assert build_breakdown("30", coupon="50").effective_price == Decimal("0.00")


def test_bad_price_rejected():
    assert build_breakdown(None) is None
    assert build_breakdown("0") is None
    assert build_breakdown("-5") is None


def test_validation():
    hist = [Decimal("1999")] * 5
    assert validate_price(Decimal("19.99"), hist).flagged
    assert not validate_price(Decimal("1499"), hist).flagged
    assert not validate_price(Decimal("19.99"), []).flagged
    assert not validate_price(Decimal("0")).valid


def test_pipeline_normalizes_and_flags():
    raw = RawOffer("jbhifi", " 123 ", "Sony  WH-1000XM6\nBlack", "https://www.jbhifi.com.au/x", "$419.00",
                   original_price="$549.00", availability="Available now", gtin="0 27242-92399", mpn="WH1000XM6B")
    n = normalize_offer(raw, history=[Decimal("500")] * 3)
    assert (n.retailer_sku, n.title, n.stock) == ("123", "Sony WH-1000XM6 Black", StockStatus.IN_STOCK)
    assert n.effective_price == Decimal("419.00") and not n.validation.flagged
    assert n.gtin == "02724292399"

    flagged = normalize_offer(RawOffer("jbhifi", "1", "t", "u", "19.99"), history=[Decimal("1999")] * 3)
    assert flagged.validation.flagged and flagged.validation.valid


def test_pipeline_invalid_price_raises_scan_error():
    with pytest.raises(ScanError) as exc:
        normalize_offer(RawOffer("jbhifi", "1", "t", "u", "n/a"))
    assert exc.value.error_type == ScanErrorType.INVALID_PRICE


def test_registry_resolves_allowlisted_https_only():
    reg = RetailerRegistry()
    reg.register(FakeAdapter())
    assert reg.resolve("https://www.jbhifi.com.au/products/x").code == "jbhifi"
    assert reg.resolve("https://jbhifi.com.au/p").code == "jbhifi"
    for bad in [
        "http://www.jbhifi.com.au/p",
        "https://evil.com/p",
        "https://jbhifi.com.au.evil.com/p",
        "https://eviljbhifi.com.au/p",
        "https://user:pw@www.jbhifi.com.au/p",
        "https://www.jbhifi.com.au:8443/p",
        "https://127.0.0.1/p",
        "file:///etc/passwd",
        "not a url",
    ]:
        with pytest.raises(UnsupportedUrl):
            reg.resolve(bad)


async def test_default_fetch_methods_delegate_and_search_optional():
    a = FakeAdapter()
    assert (await a.fetch_offer("https://www.jbhifi.com.au/x")).retailer_sku == "1"
    with pytest.raises(NotImplementedError):
        await a.search("x")
