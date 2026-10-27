"""Shared schema.org Product JSON-LD parser (source priority 3 in the design doc).

Retailer parsers are thin wrappers that supply the retailer code, seller name and
a fallback SKU pattern. The retailer's RRP is taken from a PriceSpecification with
priceType ListPrice/StrikethroughPrice/SRP, or an explicit `highPrice`, when present.
"""
import json
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from dealradar.normalization.price import parse_money
from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType

_DEFAULT_SKU_FROM_URL = re.compile(r"/products?/([^/?#]+)")
_BLOCKED = re.compile(r"captcha|are you a robot|access denied|unusual traffic", re.I)


def _iter_nodes(data):
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])
        yield data


def _is_product(node) -> bool:
    t = node.get("@type")
    return t == "Product" or (isinstance(t, list) and "Product" in t)


def _first_offer(product):
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    return offers if isinstance(offers, dict) else None


def _list_price(offer):
    if offer.get("highPrice") is not None:
        return offer["highPrice"]
    specs = offer.get("priceSpecification") or []
    if isinstance(specs, dict):
        specs = [specs]
    for spec in specs:
        if str(spec.get("priceType", "")).rsplit("/", 1)[-1] in ("ListPrice", "StrikethroughPrice", "SRP"):
            return spec.get("price")
    return None


def parse_product_jsonld(
    html: str, url: str, retailer: str, seller: str, sku_from_url: re.Pattern[str] | None = None
) -> RawOffer:
    if _BLOCKED.search(html[:4000]) and "application/ld+json" not in html:
        raise ScanError(ScanErrorType.CAPTCHA, "blocked / challenge page")
    soup = BeautifulSoup(html, "html.parser")

    product = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        product = next((n for n in _iter_nodes(data) if _is_product(n)), None)
        if product:
            break
    if product is None:
        raise ScanError(ScanErrorType.PARSE_ERROR, "no Product JSON-LD found")

    offer = _first_offer(product)
    if offer is None:
        raise ScanError(ScanErrorType.PRODUCT_REMOVED, "product has no offer")

    price = offer.get("price")
    if price is None:
        price = offer.get("lowPrice")
    original = _list_price(offer)
    # Only keep an RRP that is actually higher than the current price.
    p, o = parse_money(price), parse_money(original)
    if p is not None and o is not None and o <= p:
        original = None

    sku = product.get("sku") or product.get("mpn")
    if not sku:
        m = (sku_from_url or _DEFAULT_SKU_FROM_URL).search(url)
        sku = m.group(1) if m else None
    if not sku:
        raise ScanError(ScanErrorType.PARSE_ERROR, "no sku")

    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")

    return RawOffer(
        retailer=retailer,
        retailer_sku=str(sku),
        title=str(product.get("name") or "").strip(),
        url=url,
        price=price,
        original_price=original,
        currency=offer.get("priceCurrency") or "AUD",
        availability=offer.get("availability"),
        seller=seller,
        gtin=str(product.get("gtin13") or product.get("gtin") or "") or None,
        mpn=str(product["mpn"]) if product.get("mpn") else None,
        brand=brand,
    )
