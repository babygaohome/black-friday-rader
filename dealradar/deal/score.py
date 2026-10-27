"""Deal Score 0-100 (design doc section 23). Pure and deterministic.

Weights: historical discount 30, current discount 20, 30-day relative price 20,
90-day relative price 15, stock 5, seller confidence 5, price velocity 5.
"""
from dataclasses import dataclass
from decimal import Decimal

from dealradar.deal.fake import MIN_HISTORY_POINTS, DiscountReport
from dealradar.models.enums import StockStatus

W_HISTORICAL, W_CURRENT, W_REL30, W_REL90, W_STOCK, W_SELLER, W_VELOCITY = 30, 20, 20, 15, 5, 5, 5
FULL_CURRENT_DISCOUNT = 0.30  # an RRP discount of 30% earns the full 20 points
FULL_RELATIVE_DISCOUNT = 0.20  # 20% below the 30/90-day average earns the full points
UNVERIFIED_CAP = 69  # without history a price can't be called a deal, whatever the RRP says
FAKE_DISCOUNT_CREDIT = 0.25  # share of the "current discount" points kept when the RRP discount is misleading

_STOCK_POINTS = {
    StockStatus.IN_STOCK: 5, StockStatus.LOW_STOCK: 4, StockStatus.PREORDER: 2,
    StockStatus.BACKORDER: 1, StockStatus.OUT_OF_STOCK: 0, StockStatus.UNKNOWN: 0,
}


@dataclass(frozen=True)
class DealInput:
    price: Decimal  # effective price
    stock: StockStatus
    report: DiscountReport
    avg_30d: Decimal | None = None  # prior to the current observation
    avg_90d: Decimal | None = None
    all_time_low: Decimal | None = None  # prior to the current observation
    history_points: int = 0
    seller_confidence: float = 0.8  # 0..1
    recent_drop_pct: float = 0.0  # drop vs the previous observation / last 24h


@dataclass(frozen=True)
class DealScore:
    score: int
    grade: str
    verified: bool  # enough history to trust the relative-price components
    new_all_time_low: bool
    components: dict[str, float]


def grade(score: int) -> str:
    if score >= 95:
        return "EXTREME"
    if score >= 85:
        return "VERY_GOOD"
    if score >= 70:
        return "GOOD"
    if score >= 50:
        return "NORMAL"
    return "IGNORE"


def _ratio(x: float, full_at: float) -> float:
    return max(0.0, min(1.0, x / full_at))


def _rel(avg: Decimal | None, price: Decimal) -> float:
    return float((avg - price) / avg) if avg and avg > 0 else 0.0


def score_deal(d: DealInput) -> DealScore:
    verified = d.history_points >= MIN_HISTORY_POINTS
    new_low = bool(verified and d.all_time_low is not None and d.price < d.all_time_low)

    # Historical discount: at/below the all-time low is full marks, fading to zero 15% above it.
    if verified and d.all_time_low:
        above = float((d.price - d.all_time_low) / d.all_time_low)
        historical = W_HISTORICAL if above <= 0 else W_HISTORICAL * max(0.0, 1 - above / 0.15)
    else:
        historical = 0.0

    # Headline discount counts, but little if it is inflated.
    retailer = (d.report.retailer_discount_pct or 0) / 100
    current = W_CURRENT * _ratio(retailer, FULL_CURRENT_DISCOUNT)
    if d.report.verdict == "MISLEADING":
        current *= FAKE_DISCOUNT_CREDIT

    rel30 = W_REL30 * _ratio(_rel(d.avg_30d, d.price), FULL_RELATIVE_DISCOUNT) if verified else 0.0
    rel90 = W_REL90 * _ratio(_rel(d.avg_90d, d.price), FULL_RELATIVE_DISCOUNT) if verified else 0.0
    stock = float(_STOCK_POINTS[d.stock])
    seller = W_SELLER * max(0.0, min(1.0, d.seller_confidence))
    velocity = W_VELOCITY * _ratio(d.recent_drop_pct, 15.0)

    parts = {
        "historical": historical, "current_discount": current, "relative_30d": rel30,
        "relative_90d": rel90, "stock": stock, "seller": seller, "velocity": velocity,
    }
    total = round(sum(parts.values()))
    if not verified:
        total = min(total, UNVERIFIED_CAP)
    if d.stock == StockStatus.OUT_OF_STOCK:
        total = min(total, 49)  # can't buy it, so it is not a deal
    total = max(0, min(100, total))
    return DealScore(total, grade(total), verified, new_low, {k: round(v, 1) for k, v in parts.items()})
