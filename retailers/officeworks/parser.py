"""Officeworks product page parser (schema.org JSON-LD)."""
import re

from dealradar.retailers.base import RawOffer
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "officeworks"
_SKU_FROM_URL = re.compile(r"/p/([^/?#]+)")


def parse_product(html: str, url: str) -> RawOffer:
    return parse_product_jsonld(html, url, RETAILER, "Officeworks", _SKU_FROM_URL)
