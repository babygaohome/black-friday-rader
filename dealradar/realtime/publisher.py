"""Turns domain events into realtime messages. Failures here must never break scanning or alerting."""
import logging
import uuid

from dealradar.events import EventBus, PriceChanged, StockChanged
from dealradar.models import Alert, Offer, Product
from dealradar.realtime import hub as h
from dealradar.services.deals import analyze_offer

log = logging.getLogger(__name__)

DEAL_MIN_SCORE = 85  # "hot" grade and above is announced as deal.created
# During Black Friday nearly everything is discounted, so announce only the strongest deals.
# The spec gives no rule; this is an assumption, override with DEALRADAR_BLACK_FRIDAY_DEAL_MIN_SCORE.
BLACK_FRIDAY_DEAL_MIN_SCORE = 90


def deal_min_score(event_mode: str, normal: int = DEAL_MIN_SCORE, black_friday: int = BLACK_FRIDAY_DEAL_MIN_SCORE) -> int:
    return black_friday if event_mode.upper() == "BLACK_FRIDAY" else normal


class RealtimePublisher:
    def __init__(self, session_factory, broadcaster: h.Broadcaster, deal_min_score: int = DEAL_MIN_SCORE) -> None:
        self._sf = session_factory
        self._out = broadcaster
        self._deal_min = deal_min_score

    async def _send(self, event: str, data: dict, user_id: str | None = None) -> None:
        try:
            await self._out.publish(h.make_message(event, data, user_id))
        except Exception:
            log.exception("realtime publish failed: %s", event)

    async def _context(self, session, offer_id: uuid.UUID):
        offer = await session.get(Offer, offer_id)
        if offer is None:
            return None, None, None
        await session.refresh(offer, ["retailer"])
        product = await session.get(Product, offer.product_id) if offer.product_id else None
        return offer, offer.retailer.code, product

    async def on_price_changed(self, event: PriceChanged) -> None:
        try:
            async with self._sf() as session:
                offer, retailer, product = await self._context(session, event.offer_id)
                if offer is None:
                    return
                base = {
                    "offer_id": str(offer.id), "product_id": str(offer.product_id) if offer.product_id else None,
                    "product": product.name if product else offer.title, "retailer": retailer,
                }
                await self._send(h.PRICE_UPDATED, {
                    **base, "old_price": event.old_price, "price": event.new_price,
                    "original_price": event.original_price, "stock": event.stock.value,
                })
                dropped = event.old_price is not None and event.new_price < event.old_price
                if dropped:
                    analysis = await analyze_offer(session, offer, event.timestamp)
                    if analysis and analysis.score.score >= self._deal_min:
                        await self._send(h.DEAL_CREATED, {
                            **base, "price": event.new_price, "deal_score": analysis.score.score,
                            "grade": analysis.score.grade, "verified": analysis.score.verified,
                            "discount_verdict": analysis.discount.verdict,
                            "actual_discount_pct": analysis.discount.actual_discount_pct,
                        })
        except Exception:
            log.exception("on_price_changed failed")

    async def on_stock_changed(self, event: StockChanged) -> None:
        try:
            async with self._sf() as session:
                offer, retailer, product = await self._context(session, event.offer_id)
                if offer is None:
                    return
                await self._send(h.STOCK_UPDATED, {
                    "offer_id": str(offer.id), "product_id": str(offer.product_id) if offer.product_id else None,
                    "product": product.name if product else offer.title, "retailer": retailer,
                    "from": event.from_status.value, "to": event.to_status.value, "price": event.price,
                })
        except Exception:
            log.exception("on_stock_changed failed")

    async def on_alert(self, alert: Alert) -> None:
        await self._send(h.ALERT_TRIGGERED, {
            "alert_id": str(alert.id), "type": alert.type.value, "product_id": str(alert.product_id) if alert.product_id else None,
            "offer_id": str(alert.offer_id) if alert.offer_id else None, "price": alert.price,
            "previous_price": alert.previous_price, "deal_score": alert.deal_score,
        }, user_id=str(alert.user_id))

    async def on_scan(self, retailer: str, offer_id: uuid.UUID, status: str, error_type: str | None) -> None:
        await self._send(h.SCANNER_STATUS, {
            "retailer": retailer, "offer_id": str(offer_id), "status": status, "error_type": error_type,
        })

    def register(self, bus: EventBus) -> None:
        bus.subscribe(PriceChanged, self.on_price_changed)
        bus.subscribe(StockChanged, self.on_stock_changed)
