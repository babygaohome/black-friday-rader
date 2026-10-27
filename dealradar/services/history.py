import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import PriceHistory, StockStatus


@dataclass
class PriceMetrics:
    current: Decimal | None
    low_7d: Decimal | None
    low_30d: Decimal | None
    low_90d: Decimal | None
    avg_7d: Decimal | None
    avg_30d: Decimal | None
    avg_90d: Decimal | None
    all_time_low: Decimal | None
    volatility: float  # stdev / mean over 30d, 0 when not enough data


async def record_snapshot(
    session: AsyncSession,
    offer_id: uuid.UUID,
    price: Decimal,
    effective_price: Decimal | None = None,
    original_price: Decimal | None = None,
    stock_status: StockStatus = StockStatus.UNKNOWN,
    flagged: bool = False,
    timestamp: datetime | None = None,
) -> PriceHistory:
    row = PriceHistory(
        offer_id=offer_id,
        price=price,
        effective_price=effective_price if effective_price is not None else price,
        original_price=original_price,
        stock_status=stock_status,
        flagged=flagged,
    )
    if timestamp is not None:
        row.timestamp = timestamp
    session.add(row)
    await session.flush()
    return row


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def compute_metrics(session: AsyncSession, offer_id: uuid.UUID, now: datetime | None = None) -> PriceMetrics:
    """Historical indicators from effective_price; flagged (suspicious) rows are excluded."""
    now = now or datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(PriceHistory.effective_price, PriceHistory.timestamp)
            .where(PriceHistory.offer_id == offer_id, PriceHistory.flagged.is_(False))
            .order_by(PriceHistory.timestamp)
        )
    ).all()
    points = [(Decimal(p), _aware(ts)) for p, ts in rows]

    def window(days: int) -> list[Decimal]:
        cutoff = now - timedelta(days=days)
        return [p for p, ts in points if ts >= cutoff]

    def low(vals: list[Decimal]) -> Decimal | None:
        return min(vals) if vals else None

    def avg(vals: list[Decimal]) -> Decimal | None:
        return (sum(vals) / len(vals)).quantize(Decimal("0.01")) if vals else None

    w7, w30, w90 = window(7), window(30), window(90)
    vol = 0.0
    if len(w30) >= 2:
        mean = statistics.fmean(float(v) for v in w30)
        vol = statistics.pstdev(float(v) for v in w30) / mean if mean else 0.0

    return PriceMetrics(
        current=points[-1][0] if points else None,
        low_7d=low(w7), low_30d=low(w30), low_90d=low(w90),
        avg_7d=avg(w7), avg_30d=avg(w30), avg_90d=avg(w90),
        all_time_low=low([p for p, _ in points]),
        volatility=round(vol, 4),
    )


@dataclass
class PriorStats:
    """Statistics over valid history *before* the newest observation, so "normal price" and "all-time low"
    are not contaminated by the price being judged."""
    count: int
    all_time_low: Decimal | None
    low_30d: Decimal | None
    low_90d: Decimal | None
    avg_30d: Decimal | None
    avg_90d: Decimal | None
    latest: Decimal | None  # the newest valid observation (the price being judged)
    previous: Decimal | None  # the observation before it


async def prior_stats(session: AsyncSession, offer_id: uuid.UUID, now: datetime | None = None) -> PriorStats:
    now = now or datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(PriceHistory.effective_price, PriceHistory.timestamp)
            .where(PriceHistory.offer_id == offer_id, PriceHistory.flagged.is_(False))
            .order_by(PriceHistory.timestamp, PriceHistory.id)
        )
    ).all()
    points = [(Decimal(p), _aware(ts)) for p, ts in rows]
    latest = points[-1][0] if points else None
    previous = points[-2][0] if len(points) >= 2 else None
    prior = points[:-1]

    def window(days: int) -> list[Decimal]:
        cutoff = now - timedelta(days=days)
        return [p for p, ts in prior if ts >= cutoff]

    def low(vals):
        return min(vals) if vals else None

    def avg(vals):
        return (sum(vals) / len(vals)).quantize(Decimal("0.01")) if vals else None

    w30, w90 = window(30), window(90)
    return PriorStats(len(prior), low([p for p, _ in prior]), low(w30), low(w90), avg(w30), avg(w90), latest, previous)
