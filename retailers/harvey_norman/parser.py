"""Harvey Norman product page parser (schema.org JSON-LD).

Checked against real pages fetched 2026-10-27: the JSON-LD Product carries sku, gtin,
brand, price and availability (InStock / OutOfStock / PreOrder). "Coming soon" items
are marked OutOfStock. There is no mpn and no was/RRP price in the static page, so
original_price stays empty for this retailer.
"""
import re

from dealradar.retailers.base import RawOffer
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "harveynorman"
_SKU_FROM_URL = re.compile(r"/([^/?#]+?)(?:\.html)?/?(?:[?#].*)?$")


def parse_product(html: str, url: str) -> RawOffer:
    return parse_product_jsonld(html, url, RETAILER, "Harvey Norman", _SKU_FROM_URL)
