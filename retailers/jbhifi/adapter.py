from typing import Awaitable, Callable

import httpx

from dealradar.retailers.base import RawOffer, RetailerAdapter, ScanError, ScanErrorType
from retailers.jbhifi.parser import parse_product

Fetcher = Callable[[str], Awaitable[httpx.Response]]

USER_AGENT = "DealRadarBot/0.1 (+price monitoring; respects 429/403 with backoff)"


class JBHiFiAdapter(RetailerAdapter):
    code = "jbhifi"
    name = "JB Hi-Fi"
    domains = ("jbhifi.com.au",)

    def __init__(self, fetcher: Fetcher | None = None, timeout: float = 15.0):
        self._fetcher = fetcher
        self._timeout = timeout

    async def _get(self, url: str) -> httpx.Response:
        if self._fetcher:
            return await self._fetcher(url)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            return await client.get(url)

    async def fetch_product(self, url: str) -> RawOffer:
        if not self.owns_url(url):
            raise ScanError(ScanErrorType.UNKNOWN, "url not owned by jbhifi")
        try:
            resp = await self._get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ScanError(ScanErrorType.NETWORK_ERROR, str(exc)) from exc
        status = resp.status_code
        if status == 429:
            raise ScanError(ScanErrorType.RATE_LIMIT, "HTTP 429")
        if status == 403:
            raise ScanError(ScanErrorType.CAPTCHA, "HTTP 403")  # back off; never bypass
        if status in (404, 410):
            raise ScanError(ScanErrorType.PRODUCT_REMOVED, f"HTTP {status}")
        if 300 <= status < 400:
            raise ScanError(ScanErrorType.UNKNOWN, f"unexpected redirect {status}")  # redirects could leave the allowlist
        if status >= 500:
            raise ScanError(ScanErrorType.NETWORK_ERROR, f"HTTP {status}")
        if status != 200:
            raise ScanError(ScanErrorType.UNKNOWN, f"HTTP {status}")
        return parse_product(resp.text, url)
