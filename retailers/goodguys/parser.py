"""The Good Guys product page parser (schema.org JSON-LD)."""
import re

from dealradar.retailers.base import RawOffer
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "goodguys"
_SKU_FROM_URL = re.compile(r"/([^/?#]+)/?(?:[?#].*)?$")


def parse_product(html: str, url: str) -> RawOffer:
    return parse_product_jsonld(html, url, RETAILER, "The Good Guys", _SKU_FROM_URL)
