"""Officeworks product page parser.

Real Officeworks product pages (checked 2026-10-27) carry no schema.org JSON-LD.
The product and its price are server-rendered into `window.__INITIAL_STATE__`:
`owProduct.product` (sku, name, gtin, brand, manufacturerPartNumber, edlpPrice) and
`owProductPrice.price[<sku>].price` in cents. Stock is not in the static page (the
site loads it client-side), so availability is left unknown. Officeworks shows no
was/RRP price on product pages, so original_price is never set from this source.
The JSON-LD parser stays as a fallback for pages that do carry it.
"""
import json
import re
from decimal import Decimal

from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "officeworks"
SELLER = "Officeworks"
_SKU_FROM_URL = re.compile(r"/p/([^/?#]+)")
_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*")


def _initial_state(html: str) -> dict | None:
    m = _STATE.search(html)
    if not m:
        return None
    try:
        state = json.JSONDecoder().raw_decode(html, m.end())[0]
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _price(state: dict, product: dict, sku: str):
    entry = ((state.get("owProductPrice") or {}).get("price") or {}).get(sku) or {}
    cents = entry.get("price")
    if isinstance(cents, int) and not isinstance(cents, bool):
        return Decimal(cents) / 100
    return product.get("edlpPrice")


def parse_product(html: str, url: str) -> RawOffer:
    state = _initial_state(html)
    product = ((state or {}).get("owProduct") or {}).get("product") or {}
    if not product.get("sku"):
        return parse_product_jsonld(html, url, RETAILER, SELLER, _SKU_FROM_URL)
    if product.get("published") is False:
        raise ScanError(ScanErrorType.PRODUCT_REMOVED, "product not published")

    sku = str(product["sku"])
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    return RawOffer(
        retailer=RETAILER,
        retailer_sku=sku,
        title=str(product.get("name") or "").strip(),
        url=url,
        price=_price(state, product, sku),
        currency="AUD",
        availability=None,
        seller=SELLER,
        gtin=str(product["gtin"]) if product.get("gtin") else None,
        mpn=str(product["manufacturerPartNumber"]) if product.get("manufacturerPartNumber") else None,
        brand=brand or None,
    )
