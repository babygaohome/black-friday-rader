"""JB Hi-Fi product page parser (schema.org JSON-LD).

On 2026-10-27 real JB Hi-Fi product pages answered our scanner's User-Agent with
HTTP 429 and a Cloudflare "Verifying your connection..." JavaScript challenge
(fixtures/jbhifi_real_challenge_429.html). That is a bot block, not a rate limit;
we never try to solve or bypass it, we only classify it as CAPTCHA so the scheduler
backs off slowly and retailer health shows the real reason.
"""
import re

from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType
from dealradar.retailers.jsonld import parse_product_jsonld

RETAILER = "jbhifi"
_SKU_FROM_URL = re.compile(r"/products/([^/?#]+)")
_CHALLENGE = re.compile(r"_cf_chl_opt|challenge-error-text|Verifying your connection|connection needs to be verified", re.I)


def is_challenge_page(html: str) -> bool:
    return bool(_CHALLENGE.search(html[:20000]))


def parse_product(html: str, url: str) -> RawOffer:
    if is_challenge_page(html):
        raise ScanError(ScanErrorType.CAPTCHA, "bot challenge page")
    return parse_product_jsonld(html, url, RETAILER, "JB Hi-Fi", _SKU_FROM_URL)
