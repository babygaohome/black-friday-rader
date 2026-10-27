"""Decides which offers are due for a scan right now (M06)."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import Offer, Priority, RetailerHealth, WatchItem
from dealradar.scanning.schedule import queue_for, scan_interval

_RANK = {Priority.LOW: 0, Priority.NORMAL: 1, Priority.HIGH: 2, Priority.CRITICAL: 3}


@dataclass(frozen=True)
class DueScan:
    offer_id: uuid.UUID
    priority: Priority
    queue: str


async def due_scans(
    session: AsyncSession, now: datetime | None = None, event_mode: str = "NORMAL", limit: int = 500
) -> list[DueScan]:
    """Offers with at least one active watcher whose next scan time has passed, most urgent first."""
    now = now or datetime.now(timezone.utc)
    watch_rows = (
        await session.execute(
            select(Offer.id, WatchItem.priority)
            .join(WatchItem, WatchItem.product_id == Offer.product_id)
            .where(WatchItem.active.is_(True), Offer.active.is_(True))
        )
    ).all()
    best: dict[uuid.UUID, Priority] = {}
    for offer_id, prio in watch_rows:
        if offer_id not in best or _RANK[prio] > _RANK[best[offer_id]]:
            best[offer_id] = prio
    if not best:
        return []

    offers = (await session.execute(select(Offer).where(Offer.id.in_(best)))).scalars().all()
    health = {h.retailer_id: h for h in (await session.execute(select(RetailerHealth))).scalars()}

    due: list[tuple[float, DueScan]] = []
    for o in offers:
        prio = best[o.id]
        h = health.get(o.retailer_id)
        interval = scan_interval(
            prio,
            health_status=h.status if h else "ONLINE",
            success_rate=float(h.success_rate) if h else 1.0,
            event_mode=event_mode,
        )
        last = o.last_scanned_at
        if last is None:
            overdue = float("inf")
        else:
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            overdue = (now - last - interval).total_seconds()
            if overdue < 0:
                continue
        due.append((overdue, DueScan(o.id, prio, queue_for(prio))))
    due.sort(key=lambda t: (-_RANK[t[1].priority], -t[0]))
    return [d for _, d in due[:limit]]
