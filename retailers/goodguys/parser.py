"""The Good Guys product page parser (schema.org JSON-LD).

Calibrated against real pages fetched 2026-10-27:
- Sale prices come as offers.priceSpecification priceType StrikethroughPrice (the
  "TICKET" price shown slashed on the page); the shared JSON-LD parser reads it.
- The model number is in Product.model, not mpn; it is used as the MPN for matching.
- "Coming soon" products have a Product node with no offers at all. They are not
  removed: the page still shows the expected price under a COMING SOON ribbon, so
  they are reported as not purchasable (out of stock) at that price.
- Agency-supplied products (e.g. some Fisher & Paykel) have an offer without
  availability; stock is then unknown.
"""
import json
import re

from bs4 import BeautifulSoup

from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType
from dealradar.retailers.jsonld import _is_product, _iter_nodes, parse_product_jsonld

RETAILER = "goodguys"
SELLER = "The Good Guys"
_SKU_FROM_URL = re.compile(r"/([^/?#]+)/?(?:[?#].*)?$")
_COMING_SOON = re.compile(r"coming\s+soon", re.I)
NOT_PURCHASABLE = "https://schema.org/OutOfStock"


def _product_node(soup: BeautifulSoup) -> dict | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        node = next((n for n in _iter_nodes(data) if _is_product(n)), None)
        if node:
            return node
    return None


def _testid_text(soup: BeautifulSoup, testid: str) -> str:
    el = soup.find(attrs={"data-testid": testid})
    return el.get_text("", strip=True) if el else ""


def _coming_soon(soup: BeautifulSoup, product: dict, url: str) -> RawOffer | None:
    if not _COMING_SOON.search(_testid_text(soup, "price-section-promo-ribbon")):
        return None
    sku = product.get("sku") or (m.group(1) if (m := _SKU_FROM_URL.search(url)) else None)
    if not sku:
        return None
    brand = product.get("brand")
    return RawOffer(
        retailer=RETAILER,
        retailer_sku=str(sku),
        title=str(product.get("name") or "").strip(),
        url=url,
        price=_testid_text(soup, "price-section-price") or None,
        availability=NOT_PURCHASABLE,
        seller=SELLER,
        gtin=str(product.get("gtin13") or product.get("gtin") or "") or None,
        mpn=str(product.get("mpn") or product.get("model") or "") or None,
        brand=brand.get("name") if isinstance(brand, dict) else brand,
    )


def parse_product(html: str, url: str) -> RawOffer:
    try:
        raw = parse_product_jsonld(html, url, RETAILER, SELLER, _SKU_FROM_URL)
    except ScanError as err:
        if err.error_type != ScanErrorType.PRODUCT_REMOVED:
            raise
        soup = BeautifulSoup(html, "html.parser")
        product = _product_node(soup)
        offer = _coming_soon(soup, product, url) if product else None
        if offer is None:
            raise
        return offer
    if raw.mpn is None:
        product = _product_node(BeautifulSoup(html, "html.parser")) or {}
        if product.get("model"):
            raw.mpn = str(product["model"])
    return raw
