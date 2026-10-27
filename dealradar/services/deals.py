"""Deal analysis for an offer: history-aware score plus fake-discount check (M12). Read-only."""
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.deal.fake import DiscountReport, assess_discount
from dealradar.deal.score import DealInput, DealScore, score_deal
from dealradar.models import Offer, StockStatus
from dealradar.services.history import prior_stats

TRUSTED_RETAILERS = {"amazon_au", "jbhifi", "officeworks", "goodguys", "harveynorman"}


@dataclass(frozen=True)
class DealAnalysis:
    offer_id: uuid.UUID
    price: Decimal
    score: DealScore
    discount: DiscountReport


async def analyze_offer(session: AsyncSession, offer: Offer, now: datetime | None = None) -> DealAnalysis | None:
    """None when the offer has no usable price yet."""
    price = offer.current_effective_price
    if price is None:
        return None
    stats = await prior_stats(session, offer.id, now)
    report = assess_discount(price, offer.original_price, stats.avg_30d, stats.count)

    drop = 0.0
    if stats.previous and stats.previous > price:
        drop = float((stats.previous - price) / stats.previous * 100)
    await session.refresh(offer, ["retailer"])
    score = score_deal(DealInput(
        price=price,
        stock=offer.stock_status or StockStatus.UNKNOWN,
        report=report,
        avg_30d=stats.avg_30d,
        avg_90d=stats.avg_90d,
        all_time_low=stats.all_time_low,
        history_points=stats.count,
        seller_confidence=1.0 if offer.retailer.code in TRUSTED_RETAILERS else 0.7,
        recent_drop_pct=drop,
    ))
    return DealAnalysis(offer.id, price, score, report)
