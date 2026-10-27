"""Retailer adapter framework (M04).

Every retailer is integrated through a RetailerAdapter; business code never
contains retailer-specific parsing. Adapters return RawOffer; normalization
and validation happen downstream (dealradar.normalization).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from urllib.parse import urlparse


class ScanErrorType(str, Enum):
    NETWORK_ERROR = "NETWORK_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    CAPTCHA = "CAPTCHA"
    PARSE_ERROR = "PARSE_ERROR"
    PRODUCT_REMOVED = "PRODUCT_REMOVED"
    INVALID_PRICE = "INVALID_PRICE"
    UNKNOWN = "UNKNOWN"


class ScanError(Exception):
    def __init__(self, error_type: ScanErrorType, message: str = ""):
        super().__init__(f"{error_type.value}: {message}" if message else error_type.value)
        self.error_type = error_type


class UnsupportedUrl(ValueError):
    pass


@dataclass
class RawOffer:
    """What a parser extracted, before normalization. Raw retailer strings are kept as-is."""

    retailer: str
    retailer_sku: str
    title: str
    url: str
    price: Decimal | str | float | None
    original_price: Decimal | str | float | None = None
    currency: str = "AUD"
    availability: str | None = None  # retailer's own wording, e.g. "Available now"
    coupon: Decimal | str | float | None = None  # amount off
    shipping: Decimal | str | float | None = None
    seller: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    brand: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class RetailerAdapter(ABC):
    code: str  # e.g. "jbhifi"
    name: str
    domains: tuple[str, ...]  # allowlisted hosts (registrable domain), e.g. ("jbhifi.com.au",)

    def owns_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in self.domains)

    @abstractmethod
    async def fetch_product(self, url: str) -> RawOffer: ...

    async def fetch_offer(self, url: str) -> RawOffer:
        return await self.fetch_product(url)

    async def fetch_stock(self, url: str) -> RawOffer:
        return await self.fetch_product(url)

    async def search(self, query: str) -> list[RawOffer]:
        raise NotImplementedError(f"{self.code} does not support search")
