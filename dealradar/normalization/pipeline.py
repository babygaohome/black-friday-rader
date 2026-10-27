from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from dealradar.models.enums import StockStatus
from dealradar.normalization.price import PriceBreakdown, build_breakdown
from dealradar.normalization.stock import normalize_stock
from dealradar.normalization.validation import ValidationResult, validate_price
from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType


@dataclass(frozen=True)
class NormalizedOffer:
    retailer: str
    retailer_sku: str
    title: str
    url: str
    currency: str
    price: PriceBreakdown
    stock: StockStatus
    validation: ValidationResult
    gtin: str | None
    mpn: str | None
    brand: str | None
    seller: str | None
    timestamp: datetime

    @property
    def effective_price(self) -> Decimal:
        return self.price.effective_price


def _clean_code(value: str | None) -> str | None:
    digits = "".join(ch for ch in (value or "") if ch.isalnum())
    return digits or None


def normalize_offer(raw: RawOffer, history: Sequence[Decimal] = ()) -> NormalizedOffer:
    breakdown = build_breakdown(raw.price, raw.original_price, raw.coupon, raw.shipping)
    if breakdown is None:
        raise ScanError(ScanErrorType.INVALID_PRICE, f"unusable price {raw.price!r} for {raw.retailer}:{raw.retailer_sku}")
    return NormalizedOffer(
        retailer=raw.retailer,
        retailer_sku=str(raw.retailer_sku).strip(),
        title=" ".join(raw.title.split()),
        url=raw.url,
        currency=(raw.currency or "AUD").upper(),
        price=breakdown,
        stock=normalize_stock(raw.availability),
        validation=validate_price(breakdown.effective_price, history),
        gtin=_clean_code(raw.gtin),
        mpn=_clean_code(raw.mpn),
        brand=(raw.brand or None),
        seller=raw.seller,
        timestamp=raw.timestamp,
    )
