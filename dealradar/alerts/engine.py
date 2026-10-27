"""Alert engine (M13): decides whether a user should be told. Deal analysis (scores) lives elsewhere."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.alerts.cooldown import CooldownStore, cooldown_key
from dealradar.events import PriceChanged, StockChanged
from dealradar.models import (
    Alert, AlertType, Notification, Offer, PriceHistory, StockStatus, UserPreference, WatchItem,
)

_BUYABLE = {StockStatus.IN_STOCK, StockStatus.LOW_STOCK}
_RESTOCK_FROM = {StockStatus.OUT_OF_STOCK, StockStatus.BACKORDER}


@dataclass
class AlertCandidate:
    type: AlertType
    watch: WatchItem
    price: Decimal
    previous_price: Decimal | None


async def _prior_stats(session: AsyncSession, offer_id: uuid.UUID, now: datetime):
    """All-time low and 30-day average over valid history *excluding the newest row* (the one that just triggered us)."""
    newest = (await session.execute(select(func.max(PriceHistory.id)).where(PriceHistory.offer_id == offer_id))).scalar()
    base = (PriceHistory.offer_id == offer_id, PriceHistory.flagged.is_(False), PriceHistory.id != newest)
    low = (await session.execute(select(func.min(PriceHistory.effective_price)).where(*base))).scalar()
    cutoff = now - timedelta(days=30)
    rows = (await session.execute(select(PriceHistory.effective_price, PriceHistory.timestamp).where(*base))).all()
    recent = [Decimal(p) for p, ts in rows if (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)) >= cutoff]
    avg30 = (sum(recent) / len(recent)) if recent else None
    return (Decimal(low) if low is not None else None), avg30


def evaluate_price_change(
    event: PriceChanged, offer: Offer, watch: WatchItem, prior_low: Decimal | None, prior_avg30: Decimal | None
) -> list[AlertCandidate]:
    new, old = event.new_price, event.old_price
    out: list[AlertCandidate] = []
    # Price alerts only fire on decreases (or the very first observation), never on increases.
    if old is not None and new >= old:
        return out
    buyable = event.stock != StockStatus.OUT_OF_STOCK

    def add(t: AlertType):
        out.append(AlertCandidate(t, watch, new, old))

    if watch.target_price is not None and new <= watch.target_price and buyable:
        add(AlertType.TARGET_PRICE_HIT)
    if watch.minimum_discount is not None:
        reference = prior_avg30 or offer.original_price  # real (30-day) discount beats the retailer's RRP
        if reference and reference > 0:
            discount = (reference - new) / reference * 100
            if discount >= watch.minimum_discount and buyable:
                add(AlertType.PRICE_DROP)
    if watch.notify_on_historical_low and prior_low is not None and new < prior_low and buyable:
        add(AlertType.HISTORICAL_LOW)
    return out


def evaluate_stock_change(event: StockChanged, watch: WatchItem) -> list[AlertCandidate]:
    if watch.notify_on_stock and event.from_status in _RESTOCK_FROM and event.to_status in _BUYABLE:
        return [AlertCandidate(AlertType.RESTOCK, watch, event.price or Decimal("0"), None)]
    return []


async def _emit(
    session: AsyncSession, cooldown: CooldownStore, offer: Offer, cands: list[AlertCandidate]
) -> list[tuple[Alert, list[Notification]]]:
    emitted = []
    for c in cands:
        prefs = await session.get(UserPreference, c.watch.user_id)
        minutes = prefs.default_cooldown_minutes if prefs else 10
        if not await cooldown.try_acquire(cooldown_key(c.watch.user_id, c.watch.id, c.type), minutes * 60):
            continue
        alert = Alert(
            type=c.type, user_id=c.watch.user_id, watch_item_id=c.watch.id, product_id=offer.product_id,
            offer_id=offer.id, price=c.price, previous_price=c.previous_price,
        )
        session.add(alert)
        await session.flush()
        notes = []
        channel = prefs.default_alert_channel if prefs else "telegram"
        if channel == "telegram" and prefs and prefs.telegram_chat_id:
            n = Notification(user_id=alert.user_id, alert_id=alert.id, channel="telegram")
            session.add(n)
            notes.append(n)
        emitted.append((alert, notes))
    await session.flush()
    return emitted


class AlertEngine:
    def __init__(self, session_factory, cooldown: CooldownStore, notifier=None):
        self._sf = session_factory
        self._cooldown = cooldown
        self._notifier = notifier  # optional TelegramNotifier-like with .deliver(session, notification_id)

    async def _watchers(self, session: AsyncSession, offer: Offer) -> list[WatchItem]:
        if offer.product_id is None:
            return []
        stmt = select(WatchItem).where(WatchItem.product_id == offer.product_id, WatchItem.active.is_(True))
        return list((await session.execute(stmt)).scalars())

    async def on_price_changed(self, event: PriceChanged) -> list[Alert]:
        async with self._sf() as session:
            offer = await session.get(Offer, event.offer_id)
            watchers = await self._watchers(session, offer) if offer else []
            if not watchers:
                return []
            low, avg = await _prior_stats(session, offer.id, event.timestamp)
            cands = [c for w in watchers for c in evaluate_price_change(event, offer, w, low, avg)]
            return await self._finish(session, offer, cands)

    async def on_stock_changed(self, event: StockChanged) -> list[Alert]:
        async with self._sf() as session:
            offer = await session.get(Offer, event.offer_id)
            watchers = await self._watchers(session, offer) if offer else []
            cands = [c for w in watchers for c in evaluate_stock_change(event, w)]
            return await self._finish(session, offer, cands) if cands else []

    async def _finish(self, session: AsyncSession, offer: Offer, cands: list[AlertCandidate]) -> list[Alert]:
        emitted = await _emit(session, self._cooldown, offer, cands)
        await session.commit()
        if self._notifier:
            for _, notes in emitted:
                for n in notes:
                    await self._notifier.deliver(session, n.id)
        return [a for a, _ in emitted]

    def register(self, bus) -> None:
        bus.subscribe(PriceChanged, self.on_price_changed)
        bus.subscribe(StockChanged, self.on_stock_changed)
