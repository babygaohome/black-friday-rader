"""JB Hi-Fi product page parser (schema.org JSON-LD)."""
import re

from dealradar.retailers.base import RawOffer
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "jbhifi"
_SKU_FROM_URL = re.compile(r"/products/([^/?#]+)")


def parse_product(html: str, url: str) -> RawOffer:
    return parse_product_jsonld(html, url, RETAILER, "JB Hi-Fi", _SKU_FROM_URL)
