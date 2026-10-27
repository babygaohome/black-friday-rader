import httpx

from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType
from dealradar.retailers.http_adapter import USER_AGENT, Fetcher, HttpRetailerAdapter  # noqa: F401
from retailers.jbhifi.parser import is_challenge_page, parse_product


class JBHiFiAdapter(HttpRetailerAdapter):
    code = "jbhifi"
    name = "JB Hi-Fi"
    domains = ("jbhifi.com.au",)

    async def _get(self, url: str) -> httpx.Response:
        resp = await super()._get(url)
        # JB Hi-Fi serves its bot challenge with 429/403; report it as CAPTCHA, not a rate limit.
        if resp.status_code in (403, 429) and is_challenge_page(resp.text):
            raise ScanError(ScanErrorType.CAPTCHA, f"HTTP {resp.status_code} bot challenge")
        return resp

    def parse(self, html: str, url: str) -> RawOffer:
        return parse_product(html, url)
