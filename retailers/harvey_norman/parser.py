"""Harvey Norman product page parser (schema.org JSON-LD)."""
import re

from dealradar.retailers.base import RawOffer
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "harveynorman"
_SKU_FROM_URL = re.compile(r"/([^/?#]+?)(?:\.html)?/?$")


def parse_product(html: str, url: str) -> RawOffer:
    return parse_product_jsonld(html, url, RETAILER, "Harvey Norman", _SKU_FROM_URL)
