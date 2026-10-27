import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from dealradar.core.config import Settings
from dealradar.models.enums import StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.retailers.base import ScanError, ScanErrorType
from dealradar.retailers.builtin import build_default_registry
from dealradar.retailers.registry import RetailerRegistry
from retailers.amazon_au.adapter import HOST, AmazonAUAdapter
from retailers.amazon_au.parser import asin_from_url, parse_get_items
from retailers.amazon_au.sigv4 import sign_request, signing_key

FIX = Path(__file__).parent.parent / "fixtures"
ASIN = "B0ABC12345"
URL = f"https://www.amazon.com.au/Sony-WH-1000XM6-Headphones/dp/{ASIN}/ref=sr_1_1?keywords=sony"


def load(name):
    return json.loads((FIX / name).read_text())


# ---------- signing ----------
def test_signing_key_matches_aws_documented_vector():
    key = signing_key("wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "20120215", "us-east-1", "iam")
    assert key.hex() == "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d"


def test_sign_request_is_deterministic_and_well_formed():
    kw = dict(access_key="AKID", secret_key="SECRET", region="us-west-2", service="ProductAdvertisingAPI", host=HOST,
              path="/paapi5/getitems", payload='{"a":1}', headers={"content-type": "application/json", "x-amz-target": "T"},
              now=datetime(2026, 11, 27, 1, 2, 3, tzinfo=timezone.utc))
    a, b = sign_request(**kw), sign_request(**kw)
    assert a == b and a["x-amz-date"] == "20261127T010203Z"
    auth = a["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKID/20261127/us-west-2/ProductAdvertisingAPI/aws4_request, ")
    assert "SignedHeaders=content-type;host;x-amz-date;x-amz-target" in auth
    changed = sign_request(**{**kw, "payload": '{"a":2}'})
    assert changed["Authorization"] != auth


# ---------- parsing ----------
@pytest.mark.parametrize("url,asin", [
    (URL, ASIN),
    ("https://www.amazon.com.au/dp/b0abc12345", ASIN),
    ("https://www.amazon.com.au/gp/product/B0ABC12345?th=1", ASIN),
    ("https://www.amazon.com.au/s?k=sony", None),
    ("https://www.amazon.com.au/dp/B0ABC1234", None),
])
def test_asin_from_url(url, asin):
    assert asin_from_url(url) == asin


def test_sale_listing():
    raw = parse_get_items(load("getitems_sale.json"), ASIN, URL)
    n = normalize_offer(raw)
    assert raw.retailer == "amazon_au" and raw.retailer_sku == ASIN and raw.seller == "Amazon.com.au"
    assert n.price.item_price == Decimal("449.00") and n.price.original_price == Decimal("549.00")
    assert n.stock == StockStatus.IN_STOCK
    assert (raw.brand, raw.mpn, raw.gtin) == ("Sony", "WH1000XM6B", "4548736145871")


def test_no_saving_basis_and_unavailable():
    assert normalize_offer(parse_get_items(load("getitems_normal.json"), ASIN, URL)).price.original_price is None
    assert normalize_offer(parse_get_items(load("getitems_unavailable.json"), ASIN, URL)).stock == StockStatus.OUT_OF_STOCK


@pytest.mark.parametrize("fixture,error", [
    ("getitems_no_offers.json", ScanErrorType.PRODUCT_REMOVED),
    ("getitems_throttled.json", ScanErrorType.RATE_LIMIT),
    ("getitems_not_accessible.json", ScanErrorType.PRODUCT_REMOVED),
])
def test_response_errors(fixture, error):
    with pytest.raises(ScanError) as exc:
        parse_get_items(load(fixture), ASIN, URL)
    assert exc.value.error_type == error


def test_wrong_item_returned_is_not_used():
    with pytest.raises(ScanError):
        parse_get_items(load("getitems_sale.json"), "B0ZZZZZZZZ", URL)


# ---------- adapter ----------
def adapter(status=200, body=None, capture=None):
    async def sender(url, headers, payload):
        if capture is not None:
            capture.update(url=url, headers=headers, payload=json.loads(payload))
        return httpx.Response(status, json=body if body is not None else {}, request=httpx.Request("POST", url))

    return AmazonAUAdapter("AKID", "SECRET", "tag-22", sender=sender)


async def test_fetch_signs_and_sends_getitems():
    seen = {}
    raw = await adapter(body=load("getitems_sale.json"), capture=seen).fetch_product(URL)
    assert raw.price == 449.0
    assert seen["url"] == "https://webservices.amazon.com.au/paapi5/getitems"
    assert seen["payload"]["ItemIds"] == [ASIN] and seen["payload"]["PartnerTag"] == "tag-22"
    assert seen["payload"]["Marketplace"] == "www.amazon.com.au"
    assert seen["headers"]["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/")
    assert "SECRET" not in json.dumps(seen["headers"])


async def test_http_errors_and_400_body_errors():
    for status, error in [(429, ScanErrorType.RATE_LIMIT), (403, ScanErrorType.CAPTCHA), (503, ScanErrorType.NETWORK_ERROR)]:
        with pytest.raises(ScanError) as exc:
            await adapter(status).fetch_product(URL)
        assert exc.value.error_type == error
    with pytest.raises(ScanError) as exc:
        await adapter(400, load("getitems_not_accessible.json")).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.PRODUCT_REMOVED


async def test_bad_inputs():
    with pytest.raises(ScanError) as exc:
        await adapter().fetch_product("https://www.amazon.com.au/s?k=sony")
    assert exc.value.error_type == ScanErrorType.PARSE_ERROR
    with pytest.raises(ScanError):
        await adapter().fetch_product(f"https://evil.com/dp/{ASIN}")

    async def boom(url, headers, payload):
        raise httpx.ConnectTimeout("t")

    with pytest.raises(ScanError) as exc:
        await AmazonAUAdapter("a", "b", "c", sender=boom).fetch_product(URL)
    assert exc.value.error_type == ScanErrorType.NETWORK_ERROR


# ---------- registration ----------
def test_registered_only_when_credentials_configured():
    assert "amazon_au" not in build_default_registry(Settings()).codes()
    assert "amazon_au" not in build_default_registry(Settings(amazon_paapi_access_key="a")).codes()
    full = Settings(amazon_paapi_access_key="a", amazon_paapi_secret_key="b", amazon_paapi_partner_tag="c-22")
    reg = build_default_registry(full)
    assert "amazon_au" in reg.codes() and reg.resolve(URL).code == "amazon_au"


def test_domain_lookalikes_rejected():
    reg = RetailerRegistry()
    reg.register(AmazonAUAdapter("a", "b", "c"))
    for bad in ["https://amazon.com.au.evil.com/dp/B0ABC12345", "https://evilamazon.com.au/dp/B0ABC12345", "http://www.amazon.com.au/dp/B0ABC12345"]:
        with pytest.raises(Exception):
            reg.resolve(bad)
