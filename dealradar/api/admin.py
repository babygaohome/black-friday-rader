"""Admin panel API (M18). Every route requires an admin user; admins are made with `python -m dealradar.cli make-admin`."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from dealradar.admin_ops import QueueStats, WorkerStats
from dealradar.models import User
from dealradar.services import admin as svc
from dealradar.services import match_review


def build_admin_router(db, current_user, registered_codes, queue_stats: QueueStats | None, worker_stats: WorkerStats | None) -> APIRouter:
    async def admin_user(user: User = Depends(current_user)) -> User:
        if not user.is_admin:
            raise HTTPException(403, "admin only")
        return user

    router = APIRouter(prefix="/admin", dependencies=[Depends(admin_user)])

    @router.get("/overview")
    async def overview(session=Depends(db)):
        return await svc.overview(session)

    @router.get("/retailers")
    async def retailers(session=Depends(db)):
        return await svc.retailer_overview(session, set(registered_codes()))

    @router.get("/queues")
    async def queues():
        if queue_stats is None:
            return {"available": False, "queues": {}}
        try:
            return {"available": True, "queues": await queue_stats()}
        except Exception:
            return {"available": False, "queues": {}}

    @router.get("/workers")
    async def workers():
        if worker_stats is None:
            return {"available": False, "workers": []}
        try:
            return {"available": True, "workers": await worker_stats()}
        except Exception:
            return {"available": False, "workers": []}

    @router.get("/jobs/failed")
    async def failed(hours: int = Query(24, ge=1, le=24 * 30), limit: int = Query(50, ge=1, le=500), session=Depends(db)):
        return await svc.failed_jobs(session, hours, limit)

    @router.get("/scraper-errors")
    async def scraper_errors(hours: int = Query(24, ge=1, le=24 * 30), session=Depends(db)):
        return await svc.scraper_errors(session, hours)

    @router.get("/prices/suspicious")
    async def suspicious(limit: int = Query(50, ge=1, le=500), session=Depends(db)):
        return await svc.suspicious_prices(session, limit)

    @router.get("/matching/reviews")
    async def reviews(limit: int = Query(100, ge=1, le=500), session=Depends(db)):
        return await svc.pending_reviews(session, limit)

    @router.post("/matching/reviews/{review_id}/confirm")
    async def confirm(review_id: uuid.UUID, session=Depends(db)):
        try:
            product = await match_review.confirm(session, review_id)
        except match_review.ReviewNotPending:
            raise HTTPException(404, "no pending review with that id")
        await session.commit()
        return {"status": "CONFIRMED", "product_id": str(product.id)}

    @router.post("/matching/reviews/{review_id}/reject")
    async def reject(review_id: uuid.UUID, session=Depends(db)):
        """Also serves as CREATE NEW PRODUCT: the offer already sits on its own canonical product, which now stays."""
        try:
            review = await match_review.reject(session, review_id)
        except match_review.ReviewNotPending:
            raise HTTPException(404, "no pending review with that id")
        await session.commit()
        return {"status": "REJECTED", "product_id": str(review.product_id)}

    return router
