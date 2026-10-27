"""Read models for the admin panel (M18). Read-only; review actions live in services.match_review."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import (
    Alert, MatchReview, Offer, PriceHistory, Product, Retailer, RetailerHealth, ReviewStatus, ScanJob, User, WatchItem,
)


def _since(hours: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(hours=hours)


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


async def overview(session: AsyncSession, now: datetime | None = None) -> dict:
    day = _since(24, now)
    last_scan = (await session.execute(select(func.max(ScanJob.finished_at)))).scalar()
    return {
        "users": await _count(session, select(func.count()).select_from(User)),
        "products": await _count(session, select(func.count()).select_from(Product)),
        "active_offers": await _count(session, select(func.count()).select_from(Offer).where(Offer.active.is_(True))),
        "active_watches": await _count(session, select(func.count()).select_from(WatchItem).where(WatchItem.active.is_(True))),
        "pending_reviews": await _count(
            session, select(func.count()).select_from(MatchReview).where(MatchReview.status == ReviewStatus.PENDING)),
        "suspicious_prices_24h": await _count(
            session, select(func.count()).select_from(PriceHistory).where(PriceHistory.flagged.is_(True), PriceHistory.timestamp >= day)),
        "failed_jobs_24h": await _count(
            session, select(func.count()).select_from(ScanJob).where(ScanJob.status == "FAILED", ScanJob.finished_at >= day)),
        "running_jobs": await _count(session, select(func.count()).select_from(ScanJob).where(ScanJob.status == "RUNNING")),
        "alerts_24h": await _count(session, select(func.count()).select_from(Alert).where(Alert.created_at >= day)),
        "last_scan_at": last_scan,
    }


async def retailer_overview(session: AsyncSession, registered: set[str], now: datetime | None = None) -> list[dict]:
    """One row per retailer: health score plus how much we scan it. `registered` = adapters loaded in this process."""
    hour = _since(1, now)
    scans = {
        r.retailer_id: r
        for r in (await session.execute(
            select(
                Offer.retailer_id,
                func.count(ScanJob.id).label("total"),
                func.sum(case((ScanJob.status == "FAILED", 1), else_=0)).label("failed"),
                func.max(ScanJob.finished_at).label("last_scan"),
            ).join(Offer, Offer.id == ScanJob.offer_id).where(ScanJob.finished_at >= hour).group_by(Offer.retailer_id)
        )).all()
    }
    offers = dict((await session.execute(
        select(Offer.retailer_id, func.count()).where(Offer.active.is_(True)).group_by(Offer.retailer_id))).all())
    rows = (await session.execute(
        select(Retailer, RetailerHealth).outerjoin(RetailerHealth, RetailerHealth.retailer_id == Retailer.id).order_by(Retailer.code)
    )).all()
    out = []
    for retailer, health in rows:
        s = scans.get(retailer.id)
        out.append({
            "code": retailer.code, "name": retailer.name, "registered": retailer.code in registered,
            "status": health.status if health else "UNKNOWN",
            "success_rate": health.success_rate if health else None,
            "error_rate": health.error_rate if health else None,
            "captcha_rate": health.captcha_rate if health else None,
            "last_success": health.last_success if health else None,
            "active_offers": offers.get(retailer.id, 0),
            "scans_last_hour": s.total if s else 0,
            "failed_last_hour": int(s.failed or 0) if s else 0,
            "last_scan_at": s.last_scan if s else None,
        })
    return out


async def failed_jobs(session: AsyncSession, hours: int = 24, limit: int = 50, now: datetime | None = None) -> list[dict]:
    rows = (await session.execute(
        select(ScanJob, Offer, Retailer)
        .join(Offer, Offer.id == ScanJob.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(ScanJob.status == "FAILED", ScanJob.finished_at >= _since(hours, now))
        .order_by(ScanJob.finished_at.desc()).limit(limit)
    )).all()
    return [{
        "job_id": str(j.id), "offer_id": str(o.id), "retailer": r.code, "url": o.url,
        "error_type": j.error_type, "finished_at": j.finished_at,
    } for j, o, r in rows]


async def scraper_errors(session: AsyncSession, hours: int = 24, now: datetime | None = None) -> list[dict]:
    """Failures grouped by retailer and error type, most frequent first."""
    rows = (await session.execute(
        select(Retailer.code, ScanJob.error_type, func.count().label("n"), func.max(ScanJob.finished_at))
        .join(Offer, Offer.id == ScanJob.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(ScanJob.status == "FAILED", ScanJob.finished_at >= _since(hours, now))
        .group_by(Retailer.code, ScanJob.error_type).order_by(func.count().desc())
    )).all()
    return [{"retailer": code, "error_type": err, "count": n, "last_seen": last} for code, err, n, last in rows]


async def suspicious_prices(session: AsyncSession, limit: int = 50) -> list[dict]:
    """Flagged observations. The offer's current price is untouched by these (the scanner never stores them as current)."""
    rows = (await session.execute(
        select(PriceHistory, Offer, Retailer)
        .join(Offer, Offer.id == PriceHistory.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(PriceHistory.flagged.is_(True)).order_by(PriceHistory.timestamp.desc()).limit(limit)
    )).all()
    return [{
        "offer_id": str(o.id), "retailer": r.code, "title": o.title, "url": o.url,
        "observed_price": h.effective_price, "current_price": o.current_effective_price, "timestamp": h.timestamp,
    } for h, o, r in rows]


async def pending_reviews(session: AsyncSession, limit: int = 100) -> list[dict]:
    rows = (await session.execute(
        select(MatchReview, Offer, Retailer)
        .join(Offer, Offer.id == MatchReview.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(MatchReview.status == ReviewStatus.PENDING).order_by(MatchReview.created_at).limit(limit)
    )).all()
    out = []
    for review, offer, retailer in rows:
        suggested = await session.get(Product, review.suggested_product_id)
        out.append({
            "id": str(review.id), "confidence": review.confidence, "method": review.method,
            "offer": {"id": str(offer.id), "retailer": retailer.code, "title": offer.title, "url": offer.url,
                      "price": offer.current_effective_price},
            "suggested_product": {"id": str(suggested.id), "name": suggested.name} if suggested else None,
            "created_at": review.created_at,
        })
    return out
