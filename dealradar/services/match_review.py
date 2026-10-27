"""Manual review of low-confidence matches (design doc section 40: CONFIRM / REJECT)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import MatchReview, Offer, Product, ReviewStatus, WatchItem


class ReviewNotPending(Exception):
    pass


async def list_pending(session: AsyncSession, limit: int = 100) -> list[MatchReview]:
    stmt = select(MatchReview).where(MatchReview.status == ReviewStatus.PENDING).order_by(MatchReview.created_at).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def _pending(session: AsyncSession, review_id: uuid.UUID) -> MatchReview:
    review = await session.get(MatchReview, review_id)
    if review is None or review.status != ReviewStatus.PENDING:
        raise ReviewNotPending(str(review_id))
    return review


async def confirm(session: AsyncSession, review_id: uuid.UUID) -> Product:
    """The offer really is the suggested product: move it (and anyone watching the stand-in product) there."""
    review = await _pending(session, review_id)
    target_id, temp_id = review.suggested_product_id, review.product_id

    offer = await session.get(Offer, review.offer_id)
    offer.product_id = target_id
    offer.match_confidence = 1  # human-confirmed

    if temp_id != target_id:
        already = select(WatchItem.user_id).where(WatchItem.product_id == target_id)
        # users watching both: keep their existing watch on the target, drop the duplicate
        await session.execute(delete(WatchItem).where(WatchItem.product_id == temp_id, WatchItem.user_id.in_(already)))
        await session.execute(update(WatchItem).where(WatchItem.product_id == temp_id).values(product_id=target_id))
        remaining = (await session.execute(
            select(func.count()).select_from(Offer).where(Offer.product_id == temp_id, Offer.id != offer.id)
        )).scalar()
        if not remaining:
            await session.flush()
            temp = await session.get(Product, temp_id)
            if temp is not None:
                await session.delete(temp)

    review.status, review.resolved_at = ReviewStatus.CONFIRMED, datetime.now(timezone.utc)
    await session.flush()
    return await session.get(Product, target_id)


async def reject(session: AsyncSession, review_id: uuid.UUID) -> MatchReview:
    """Not the same product: the offer stays on its own canonical product."""
    review = await _pending(session, review_id)
    review.status, review.resolved_at = ReviewStatus.REJECTED, datetime.now(timezone.utc)
    await session.flush()
    return review
