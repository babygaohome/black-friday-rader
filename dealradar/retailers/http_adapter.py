"""Shared HTTP behaviour for retailers served as public product pages.

Subclasses set code/name/domains and implement parse(). Error mapping follows the
compliance rules: 403/429/CAPTCHA mean back off (never bypass), redirects are not
followed (they could leave the domain allowlist).
"""
from abc import abstractmethod
from typing import Awaitable, Callable

import httpx

from dealradar.retailers.base import RawOffer, RetailerAdapter, ScanError, ScanErrorType

Fetcher = Callable[[str], Awaitable[httpx.Response]]

USER_AGENT = "DealRadarBot/0.1 (+price monitoring; respects 429/403 with backoff)"


def raise_for_status(status: int) -> None:
    if status == 200:
        return
    if status == 429:
        raise ScanError(ScanErrorType.RATE_LIMIT, "HTTP 429")
    if status == 403:
        raise ScanError(ScanErrorType.CAPTCHA, "HTTP 403")
    if status in (404, 410):
        raise ScanError(ScanErrorType.PRODUCT_REMOVED, f"HTTP {status}")
    if 300 <= status < 400:
        raise ScanError(ScanErrorType.UNKNOWN, f"unexpected redirect {status}")
    if status >= 500:
        raise ScanError(ScanErrorType.NETWORK_ERROR, f"HTTP {status}")
    raise ScanError(ScanErrorType.UNKNOWN, f"HTTP {status}")


class HttpRetailerAdapter(RetailerAdapter):
    def __init__(self, fetcher: Fetcher | None = None, timeout: float = 15.0):
        self._fetcher = fetcher
        self._timeout = timeout

    async def _get(self, url: str) -> httpx.Response:
        if self._fetcher:
            return await self._fetcher(url)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            return await client.get(url)

    @abstractmethod
    def parse(self, html: str, url: str) -> RawOffer: ...

    async def fetch_product(self, url: str) -> RawOffer:
        if not self.owns_url(url):
            raise ScanError(ScanErrorType.UNKNOWN, f"url not owned by {self.code}")
        try:
            resp = await self._get(url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ScanError(ScanErrorType.NETWORK_ERROR, str(exc)) from exc
        raise_for_status(resp.status_code)
        return self.parse(resp.text, url)
