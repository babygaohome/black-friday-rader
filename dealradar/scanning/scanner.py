"""Scan one offer end to end (M08): fetch -> normalize -> validate -> store -> compare -> events."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.events import EventBus, PriceChanged, StockChanged
from dealradar.models import Offer, PriceHistory, RetailerHealth, ScanJob, StockStatus
from dealradar.normalization.pipeline import normalize_offer
from dealradar.retailers.base import RetailerAdapter, ScanError, ScanErrorType
from dealradar.scanning.locks import LOCK_TTL_SECONDS, LockBackend, scan_lock_key
from dealradar.services.history import record_snapshot

HISTORY_SAMPLE = 50
HEALTH_ALPHA = 0.1  # exponential moving average weight of the newest scan


@dataclass
class ScanResult:
    status: str  # OK | FLAGGED | SKIPPED_LOCKED | FAILED
    error_type: ScanErrorType | None = None
    price_changed: bool = False
    stock_changed: bool = False


async def _update_health(session: AsyncSession, retailer_id, ok: bool, error: ScanErrorType | None) -> None:
    h = await session.get(RetailerHealth, retailer_id)
    if h is None:
        h = RetailerHealth(retailer_id=retailer_id, success_rate=Decimal("1"), error_rate=Decimal("0"), captcha_rate=Decimal("0"))
        session.add(h)
    a = HEALTH_ALPHA
    h.success_rate = Decimal(str(round(float(h.success_rate) * (1 - a) + (1.0 if ok else 0.0) * a, 4)))
    h.error_rate = Decimal(str(round(1 - float(h.success_rate), 4)))
    is_captcha = error in (ScanErrorType.CAPTCHA, ScanErrorType.RATE_LIMIT)
    h.captcha_rate = Decimal(str(round(float(h.captcha_rate) * (1 - a) + (1.0 if is_captcha else 0.0) * a, 4)))
    if ok:
        h.last_success = datetime.now(timezone.utc)
    rate = float(h.success_rate)
    h.status = "ONLINE" if rate >= 0.9 else "DEGRADED" if rate >= 0.5 else "OFFLINE"


async def scan_offer(
    session: AsyncSession,
    offer: Offer,
    adapter: RetailerAdapter,
    lock: LockBackend,
    bus: EventBus,
) -> ScanResult:
    key = scan_lock_key(offer.id)
    if not await lock.acquire(key, LOCK_TTL_SECONDS):
        return ScanResult("SKIPPED_LOCKED")

    job = ScanJob(offer_id=offer.id, status="RUNNING", started_at=datetime.now(timezone.utc))
    session.add(job)
    try:
        try:
            raw = await adapter.fetch_offer(offer.url)
            hist = (
                await session.execute(
                    select(PriceHistory.effective_price)
                    .where(PriceHistory.offer_id == offer.id, PriceHistory.flagged.is_(False))
                    .order_by(PriceHistory.timestamp.desc())
                    .limit(HISTORY_SAMPLE)
                )
            ).scalars().all()
            norm = normalize_offer(raw, history=[Decimal(h) for h in hist])
        except ScanError as err:
            job.status, job.error_type = "FAILED", err.error_type.value
            job.finished_at = datetime.now(timezone.utc)
            await _update_health(session, offer.retailer_id, False, err.error_type)
            await session.commit()
            return ScanResult("FAILED", error_type=err.error_type)

        flagged = norm.validation.flagged
        await record_snapshot(
            session, offer.id, norm.price.item_price, norm.effective_price, norm.price.original_price,
            norm.stock, flagged=flagged,
        )

        old_price, old_stock = offer.current_effective_price, offer.stock_status
        price_changed = stock_changed = False
        offer.last_scanned_at = datetime.now(timezone.utc)
        if not flagged:  # suspicious data is stored for audit but never becomes the current state
            price_changed = old_price != norm.effective_price
            stock_changed = old_stock != norm.stock and old_stock != StockStatus.UNKNOWN
            offer.current_price = norm.price.item_price
            offer.current_effective_price = norm.effective_price
            offer.original_price = norm.price.original_price
            offer.stock_status = norm.stock
            offer.title = offer.title or norm.title

        job.status = "FLAGGED" if flagged else "OK"
        job.finished_at = datetime.now(timezone.utc)
        await _update_health(session, offer.retailer_id, True, None)
        await session.commit()

        if price_changed:
            await bus.publish(PriceChanged(offer.id, old_price, norm.effective_price, norm.price.original_price, norm.stock))
        if stock_changed:
            await bus.publish(StockChanged(offer.id, old_stock, norm.stock, norm.effective_price))
        return ScanResult("FLAGGED" if flagged else "OK", price_changed=price_changed, stock_changed=stock_changed)
    finally:
        await lock.release(key)
