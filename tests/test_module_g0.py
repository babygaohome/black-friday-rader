import json
import re

import httpx
import pytest

from dealradar.retailers.base import ScanError, ScanErrorType
from dealradar.retailers.http_adapter import raise_for_status
from dealradar.retailers.jsonld import parse_product_jsonld


def page(*blocks):
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    return f"<html><head>{scripts}</head><body></body></html>"


def parse(html, url="https://x.com.au/product/abc-1"):
    return parse_product_jsonld(html, url, "x", "X Store")


def test_graph_wrapper_and_type_list():
    html = page({"@graph": [{"@type": "WebSite"}, {"@type": ["Product", "Thing"], "name": "N", "sku": "S1",
                                                 "offers": {"price": 10, "priceCurrency": "AUD"}}]})
    raw = parse(html)
    assert (raw.retailer, raw.seller, raw.retailer_sku, raw.price) == ("x", "X Store", "S1", 10)


def test_offer_list_and_aggregate_offer_low_price():
    assert parse(page({"@type": "Product", "name": "N", "sku": "1", "offers": [{"price": "5.5"}, {"price": "9"}]})).price == "5.5"
    agg = parse(page({"@type": "Product", "name": "N", "sku": "1", "offers": {"@type": "AggregateOffer", "lowPrice": "7", "highPrice": "9"}}))
    assert agg.price == "7" and agg.original_price == "9"


def test_rrp_must_exceed_price_and_sku_fallbacks():
    flat = parse(page({"@type": "Product", "name": "N", "mpn": "M-1", "offers": {"price": "20", "highPrice": "20"}}))
    assert flat.original_price is None and flat.retailer_sku == "M-1"
    from_url = parse(page({"@type": "Product", "name": "N", "offers": {"price": "20"}}), "https://x.com.au/product/abc-1?x=1")
    assert from_url.retailer_sku == "abc-1"
    custom = parse_product_jsonld(page({"@type": "Product", "name": "N", "offers": {"price": "1"}}),
                                  "https://x.com.au/p/9999-widget", "x", "X", re.compile(r"/p/(\d+)"))
    assert custom.retailer_sku == "9999"


def test_skips_broken_json_and_non_product_blocks():
    html = '<script type="application/ld+json">{oops</script>' + page({"@type": "Organization"}, {"@type": "Product", "name": "N", "sku": "1", "offers": {"price": "3"}})
    assert parse(html).price == "3"


@pytest.mark.parametrize("status,error", [
    (429, ScanErrorType.RATE_LIMIT), (403, ScanErrorType.CAPTCHA), (404, ScanErrorType.PRODUCT_REMOVED),
    (410, ScanErrorType.PRODUCT_REMOVED), (301, ScanErrorType.UNKNOWN), (500, ScanErrorType.NETWORK_ERROR),
    (418, ScanErrorType.UNKNOWN),
])
def test_status_mapping(status, error):
    with pytest.raises(ScanError) as exc:
        raise_for_status(status)
    assert exc.value.error_type == error
    raise_for_status(200)
