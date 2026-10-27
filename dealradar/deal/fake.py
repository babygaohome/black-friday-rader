"""Fake discount detection (design doc section 24).

Retailers quote a discount against their own RRP, which can be inflated. We compare the
price with what the product actually cost over the previous 30 days.
"""
from dataclasses import dataclass
from decimal import Decimal

MIN_HISTORY_POINTS = 3  # fewer observations than this and we can't say what "normal" is


@dataclass(frozen=True)
class DiscountReport:
    retailer_discount_pct: float | None  # vs the retailer's RRP
    actual_discount_pct: float | None  # vs the observed 30-day normal price
    normal_price: Decimal | None
    verdict: str  # GENUINE | MISLEADING | NO_CLAIM | UNVERIFIED


def _pct(reference: Decimal, price: Decimal) -> float:
    return float((reference - price) / reference * 100)


def assess_discount(
    price: Decimal, original_price: Decimal | None, normal_price: Decimal | None, history_points: int
) -> DiscountReport:
    retailer = _pct(original_price, price) if original_price and original_price > price else None
    have_history = normal_price is not None and normal_price > 0 and history_points >= MIN_HISTORY_POINTS
    actual = _pct(normal_price, price) if have_history else None
    if actual is not None:
        actual = max(actual, 0.0) if actual > -0.05 else actual  # rounding noise around zero

    if retailer is None:
        verdict = "NO_CLAIM"
    elif actual is None:
        verdict = "UNVERIFIED"
    elif retailer >= 10 and (retailer - actual >= 15 or actual < retailer * 0.25):
        verdict = "MISLEADING"
    else:
        verdict = "GENUINE"
    return DiscountReport(
        None if retailer is None else round(retailer, 1),
        None if actual is None else round(actual, 1),
        normal_price if have_history else None,
        verdict,
    )
