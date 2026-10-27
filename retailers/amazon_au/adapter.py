"""Amazon AU via the official Product Advertising API 5.0 (design doc: official API first, no page scraping)."""
import json
from typing import Awaitable, Callable

import httpx

from dealradar.retailers.base import RawOffer, RetailerAdapter, ScanError, ScanErrorType
from dealradar.retailers.http_adapter import raise_for_status
from retailers.amazon_au.parser import asin_from_url, parse_get_items
from retailers.amazon_au.sigv4 import sign_request

HOST = "webservices.amazon.com.au"
REGION = "us-west-2"
PATH = "/paapi5/getitems"
TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.GetItems"
RESOURCES = [
    "ItemInfo.Title", "ItemInfo.ByLineInfo", "ItemInfo.ExternalIds", "ItemInfo.ManufactureInfo",
    "Offers.Listings.Price", "Offers.Listings.SavingBasis", "Offers.Listings.Availability.Type",
    "Offers.Listings.Availability.Message", "Offers.Listings.MerchantInfo",
]

Sender = Callable[[str, dict[str, str], str], Awaitable[httpx.Response]]


class AmazonAUAdapter(RetailerAdapter):
    code = "amazon_au"
    name = "Amazon Australia"
    domains = ("amazon.com.au",)

    def __init__(self, access_key: str, secret_key: str, partner_tag: str, sender: Sender | None = None, timeout: float = 15.0):
        self._access_key, self._secret_key, self._partner_tag = access_key, secret_key, partner_tag
        self._sender = sender
        self._timeout = timeout

    async def _send(self, url: str, headers: dict[str, str], body: str) -> httpx.Response:
        if self._sender:
            return await self._sender(url, headers, body)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(url, headers=headers, content=body)

    async def fetch_product(self, url: str) -> RawOffer:
        if not self.owns_url(url):
            raise ScanError(ScanErrorType.UNKNOWN, "url not owned by amazon_au")
        asin = asin_from_url(url)
        if asin is None:
            raise ScanError(ScanErrorType.PARSE_ERROR, "no ASIN in url")
        body = json.dumps({
            "ItemIds": [asin], "Resources": RESOURCES, "PartnerTag": self._partner_tag,
            "PartnerType": "Associates", "Marketplace": "www.amazon.com.au",
        })
        headers = sign_request(
            access_key=self._access_key, secret_key=self._secret_key, region=REGION, service="ProductAdvertisingAPI",
            host=HOST, path=PATH, payload=body,
            headers={"content-encoding": "amz-1.0", "content-type": "application/json; charset=utf-8", "x-amz-target": TARGET},
        )
        try:
            resp = await self._send(f"https://{HOST}{PATH}", headers, body)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ScanError(ScanErrorType.NETWORK_ERROR, str(exc)) from exc
        if resp.status_code == 400:
            # PA-API reports item-level problems in the body even on 400.
            try:
                return parse_get_items(resp.json(), asin, url)
            except ValueError:
                raise ScanError(ScanErrorType.UNKNOWN, "HTTP 400")
        raise_for_status(resp.status_code)
        try:
            data = resp.json()
        except ValueError as exc:
            raise ScanError(ScanErrorType.PARSE_ERROR, "invalid JSON") from exc
        return parse_get_items(data, asin, url)
