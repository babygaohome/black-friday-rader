import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select

from dealradar.admin_ops import QueueStats, WorkerStats
from dealradar.api.admin import build_admin_router
from dealradar.core.security import issue_token, verify_token
from dealradar.models import Alert, Offer, PriceHistory, Priority, Product, User, WatchItem
from dealradar.retailers.base import ScanError, UnsupportedUrl
from dealradar.observability.logs import log_event
from dealradar.observability.metrics import AppMetrics, db_metrics
from dealradar.realtime.hub import TOPICS, Hub, Relay, dumps
from dealradar.retailers.registry import RetailerRegistry
from dealradar.services import admin as svc_admin
from dealradar.services import watchlist as watch_svc
from dealradar.services.catalog import add_from_url
from dealradar.services.deals import DealAnalysis, analyze_offer
from dealradar.services.history import compute_metrics
from dealradar.services.users import EmailTaken, authenticate, register_user


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)
    display_name: str = ""


class FromUrl(BaseModel):
    url: str = Field(max_length=2000)


class WatchIn(BaseModel):
    product_id: uuid.UUID
    target_price: Decimal | None = Field(default=None, gt=0)
    minimum_discount: Decimal | None = Field(default=None, gt=0, le=100)
    notify_on_stock: bool = False
    notify_on_historical_low: bool = False
    priority: Priority = Priority.NORMAL


class WatchPatch(BaseModel):
    target_price: Decimal | None = Field(default=None, gt=0)
    minimum_discount: Decimal | None = Field(default=None, gt=0, le=100)
    notify_on_stock: bool | None = None
    notify_on_historical_low: bool | None = None
    priority: Priority | None = None
    active: bool | None = None


class ProfilePatch(BaseModel):
    display_name: str | None = None
    timezone: str | None = None
    telegram_chat_id: str | None = None


def _watch_out(w: WatchItem) -> dict:
    return {
        "id": str(w.id), "product_id": str(w.product_id),
        "target_price": w.target_price, "minimum_discount": w.minimum_discount,
        "notify_on_stock": w.notify_on_stock, "notify_on_historical_low": w.notify_on_historical_low,
        "priority": w.priority.value, "active": w.active,
    }


def _offer_out(o: Offer) -> dict:
    return {
        "id": str(o.id), "retailer": o.retailer.code if "retailer" in o.__dict__ else None, "url": o.url,
        "title": o.title, "price": o.current_price, "effective_price": o.current_effective_price,
        "original_price": o.original_price, "currency": o.currency, "stock": o.stock_status.value,
        "last_scanned_at": o.last_scanned_at,
    }


def _deal_out(offer: Offer, product: Product, a: DealAnalysis) -> dict:
    return {
        "product_id": str(product.id), "product": product.name, "offer_id": str(offer.id),
        "retailer": offer.retailer.code, "url": offer.url, "price": a.price,
        "stock": offer.stock_status.value, "deal_score": a.score.score, "grade": a.score.grade,
        "verified": a.score.verified, "new_all_time_low": a.score.new_all_time_low,
        "retailer_discount_pct": a.discount.retailer_discount_pct, "actual_discount_pct": a.discount.actual_discount_pct,
        "normal_price": a.discount.normal_price, "discount_verdict": a.discount.verdict,
        "last_scanned_at": offer.last_scanned_at,
    }


def create_app(session_factory, registry: RetailerRegistry, secret_key: str, token_ttl: int = 7 * 24 * 3600,
               hub: Hub | None = None, relay: Relay | None = None,
               queue_stats: QueueStats | None = None, worker_stats: WorkerStats | None = None,
               cors_origins: list[str] | None = None) -> FastAPI:
    """relay: optional long-running coroutine fed the hub (e.g. Redis pub/sub -> hub), run for the app's lifetime."""
    hub = hub or Hub()

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(relay(hub)) if relay else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="DealRadar", lifespan=lifespan)
    app.state.hub = hub
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])
    metrics = app.state.metrics = AppMetrics()
    log = logging.getLogger("dealradar.api")

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as exc:
            log_event(log, "request_failed", logging.ERROR, method=request.method, path=request.url.path, error=repr(exc))
            raise
        finally:
            route = getattr(request.scope.get("route"), "path", "unmatched")  # template, not raw path
            metrics.observe(request.method, route, status, time.perf_counter() - start)

    async def db():
        async with session_factory() as session:
            yield session

    async def current_user(session=Depends(db), authorization: str | None = Header(default=None)) -> User:
        scheme, _, token = (authorization or "").partition(" ")
        user_id = verify_token(secret_key, token) if scheme.lower() == "bearer" else None
        user = await session.get(User, uuid.UUID(user_id)) if user_id else None
        if user is None or user.status != "ACTIVE":
            raise HTTPException(401, "invalid or missing token")
        return user

    app.include_router(build_admin_router(db, current_user, registry.codes, queue_stats, worker_stats))

    @app.get("/metrics")
    async def prometheus(user: User = Depends(current_user), session=Depends(db)):
        """Prometheus scrape target; send the admin token as `Authorization: Bearer ...`."""
        if not user.is_admin:
            raise HTTPException(403, "admin only")
        lines = metrics.render(hub.size) + await db_metrics(session)
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    # ---- realtime (M17) ----
    @app.websocket("/ws")
    async def realtime(ws: WebSocket, token: str = "", topics: str = ""):
        """Browsers cannot set headers on a WebSocket, so the token travels in the query string."""
        user_id = verify_token(secret_key, token)
        wanted = {t for t in topics.split(",") if t}
        if user_id is None or not wanted <= TOPICS:
            await ws.close(code=4401 if user_id is None else 4400)
            return
        async with session_factory() as session:
            user = await session.get(User, uuid.UUID(user_id))
        if user is None or user.status != "ACTIVE":
            await ws.close(code=4401)
            return
        await ws.accept()
        client = hub.connect(user_id, wanted or None)
        await ws.send_json({"event": "connected", "data": {"topics": sorted(client.topics)}})

        async def pump():
            while True:
                await ws.send_text(dumps(await client.queue.get()))  # payloads hold Decimals, which send_json cannot encode

        async def listen():
            while True:
                msg = await ws.receive_json()
                action = msg.get("action") if isinstance(msg, dict) else None
                if action == "ping":
                    await ws.send_json({"event": "pong"})
                elif action == "subscribe" and isinstance(msg.get("topics"), list):
                    client.topics = (set(msg["topics"]) & TOPICS) or set(TOPICS)
                    await ws.send_json({"event": "subscribed", "data": {"topics": sorted(client.topics)}})

        tasks = [asyncio.create_task(pump()), asyncio.create_task(listen())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            hub.disconnect(client)
            with contextlib.suppress(Exception):
                await ws.close()

    # ---- auth / users ----
    @app.post("/auth/register", status_code=201)
    async def register(body: Credentials, session=Depends(db)):
        try:
            user = await register_user(session, body.email, body.password, body.display_name)
        except EmailTaken:
            raise HTTPException(409, "email already registered")
        await session.commit()
        return {"id": str(user.id), "token": issue_token(secret_key, str(user.id), token_ttl)}

    @app.post("/auth/login")
    async def login(body: Credentials, session=Depends(db)):
        user = await authenticate(session, body.email, body.password)
        if user is None:
            raise HTTPException(401, "invalid credentials")
        return {"token": issue_token(secret_key, str(user.id), token_ttl)}

    @app.post("/auth/logout", status_code=204)
    async def logout(user: User = Depends(current_user)):
        return None  # tokens are stateless; the client discards its token

    @app.get("/users/me")
    async def me(user: User = Depends(current_user), session=Depends(db)):
        await session.refresh(user, ["preferences"])
        return {
            "id": str(user.id), "email": user.email, "display_name": user.display_name, "timezone": user.timezone,
            "telegram_linked": bool(user.preferences and user.preferences.telegram_chat_id), "is_admin": user.is_admin,
        }

    @app.patch("/users/me")
    async def patch_me(body: ProfilePatch, user: User = Depends(current_user), session=Depends(db)):
        await session.refresh(user, ["preferences"])
        if body.display_name is not None:
            user.display_name = body.display_name
        if body.timezone is not None:
            user.timezone = body.timezone
        if body.telegram_chat_id is not None:
            user.preferences.telegram_chat_id = body.telegram_chat_id or None
        await session.commit()
        return {"ok": True}

    # ---- products ----
    @app.post("/products/from-url", status_code=201)
    async def from_url(body: FromUrl, user: User = Depends(current_user), session=Depends(db)):
        try:
            result = await add_from_url(session, registry, body.url)
        except UnsupportedUrl as exc:
            raise HTTPException(422, str(exc))
        except ScanError as exc:
            raise HTTPException(502, f"could not read product page: {exc.error_type.value}")
        await session.commit()
        return {"product_id": str(result.product.id), "offer_id": str(result.offer.id), "created": result.created,
                "name": result.product.name}

    @app.get("/retailers")
    async def retailers(user: User = Depends(current_user)):
        return [{"code": c, "name": registry.get(c).name, "domains": list(registry.get(c).domains)} for c in registry.codes()]

    @app.get("/scanner/status")
    async def scanner_status(user: User = Depends(current_user), session=Depends(db)):
        """War Room: per-retailer health and how recently each was scanned."""
        rows = await svc_admin.retailer_overview(session, set(registry.codes()))
        last = max((r["last_scan_at"] for r in rows if r["last_scan_at"]), default=None)
        return {
            "last_scan_at": last,
            "retailers": [{k: r[k] for k in ("code", "name", "status", "success_rate", "last_success", "last_scan_at")} for r in rows],
        }

    @app.get("/products")
    async def products(q: str = "", limit: int = 50, user: User = Depends(current_user), session=Depends(db)):
        stmt = select(Product).order_by(Product.created_at.desc()).limit(min(max(limit, 1), 200))
        if q.strip():
            stmt = stmt.where(Product.name.ilike(f"%{q.strip()}%"))
        return [{"id": str(p.id), "name": p.name, "brand": p.brand} for p in (await session.execute(stmt)).scalars()]

    async def _product(session, product_id: uuid.UUID) -> Product:
        p = await session.get(Product, product_id)
        if p is None:
            raise HTTPException(404, "product not found")
        return p

    @app.get("/products/{product_id}")
    async def product_detail(product_id: uuid.UUID, user: User = Depends(current_user), session=Depends(db)):
        p = await _product(session, product_id)
        offers = (await session.execute(select(Offer).where(Offer.product_id == p.id, Offer.active.is_(True)))).scalars().all()
        priced = [o for o in offers if o.current_effective_price is not None]
        best = min(priced, key=lambda o: o.current_effective_price, default=None)
        metrics = await compute_metrics(session, best.id) if best else None
        analysis = await analyze_offer(session, best) if best else None
        return {
            "id": str(p.id), "name": p.name, "brand": p.brand,
            "best_price": best.current_effective_price if best else None,
            "deal": None if analysis is None else {
                "deal_score": analysis.score.score, "grade": analysis.score.grade, "verified": analysis.score.verified,
                "new_all_time_low": analysis.score.new_all_time_low,
                "retailer_discount_pct": analysis.discount.retailer_discount_pct,
                "actual_discount_pct": analysis.discount.actual_discount_pct,
                "discount_verdict": analysis.discount.verdict,
            },
            "metrics": None if metrics is None else {
                "low_30d": metrics.low_30d, "low_90d": metrics.low_90d, "avg_30d": metrics.avg_30d,
                "all_time_low": metrics.all_time_low,
            },
        }

    @app.get("/products/{product_id}/offers")
    async def product_offers(product_id: uuid.UUID, user: User = Depends(current_user), session=Depends(db)):
        await _product(session, product_id)
        rows = (await session.execute(select(Offer).where(Offer.product_id == product_id))).scalars().all()
        out = []
        for o in rows:
            await session.refresh(o, ["retailer"])
            out.append(_offer_out(o))
        return sorted(out, key=lambda o: (o["effective_price"] is None, o["effective_price"]))

    @app.get("/products/{product_id}/history")
    async def product_history(product_id: uuid.UUID, limit: int = 500, user: User = Depends(current_user), session=Depends(db)):
        await _product(session, product_id)
        stmt = (
            select(PriceHistory, Offer.retailer_sku)
            .join(Offer, Offer.id == PriceHistory.offer_id)
            .where(Offer.product_id == product_id, PriceHistory.flagged.is_(False))
            .order_by(PriceHistory.timestamp.desc()).limit(min(max(limit, 1), 2000))
        )
        return [
            {"offer_id": str(h.offer_id), "effective_price": h.effective_price, "stock": h.stock_status.value,
             "timestamp": h.timestamp}
            for h, _ in (await session.execute(stmt)).all()
        ]

    # ---- watchlist ----
    @app.get("/watchlist")
    async def get_watchlist(user: User = Depends(current_user), session=Depends(db)):
        return [_watch_out(w) for w in await watch_svc.list_watches(session, user.id)]

    @app.post("/watchlist", status_code=201)
    async def add_watchlist(body: WatchIn, user: User = Depends(current_user), session=Depends(db)):
        await _product(session, body.product_id)
        w = await watch_svc.add_watch(
            session, user.id, body.product_id, body.target_price, body.minimum_discount,
            body.notify_on_stock, body.notify_on_historical_low, body.priority,
        )
        await session.commit()
        return _watch_out(w)

    async def _own_watch(session, user, watch_id) -> WatchItem:
        w = await session.get(WatchItem, watch_id)
        if w is None or w.user_id != user.id:
            raise HTTPException(404, "watch item not found")
        return w

    @app.patch("/watchlist/{watch_id}")
    async def patch_watchlist(watch_id: uuid.UUID, body: WatchPatch, user: User = Depends(current_user), session=Depends(db)):
        w = await _own_watch(session, user, watch_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(w, field, value)
        await session.commit()
        return _watch_out(w)

    @app.delete("/watchlist/{watch_id}", status_code=204)
    async def delete_watchlist(watch_id: uuid.UUID, user: User = Depends(current_user), session=Depends(db)):
        await _own_watch(session, user, watch_id)
        await watch_svc.deactivate_watch(session, user.id, watch_id)
        await session.commit()

    # ---- alerts ----
    @app.get("/alerts")
    async def get_alerts(limit: int = 50, user: User = Depends(current_user), session=Depends(db)):
        stmt = select(Alert).where(Alert.user_id == user.id).order_by(Alert.created_at.desc()).limit(min(max(limit, 1), 200))
        return [
            {"id": str(a.id), "type": a.type.value, "product_id": str(a.product_id), "price": a.price,
             "previous_price": a.previous_price, "deal_score": a.deal_score, "read": a.read, "created_at": a.created_at}
            for a in (await session.execute(stmt)).scalars()
        ]

    @app.post("/alerts/{alert_id}/read", status_code=204)
    async def read_alert(alert_id: uuid.UUID, user: User = Depends(current_user), session=Depends(db)):
        a = await session.get(Alert, alert_id)
        if a is None or a.user_id != user.id:
            raise HTTPException(404, "alert not found")
        a.read = True
        await session.commit()

    # ---- deals ----
    async def _analyzed(session, limit: int, order_scanned: bool = False):
        stmt = select(Offer, Product).join(Product, Product.id == Offer.product_id).where(
            Offer.active.is_(True), Offer.current_effective_price.is_not(None))
        stmt = stmt.order_by(Offer.last_scanned_at.desc().nulls_last()).limit(min(max(limit, 1), 200))
        out = []
        for offer, product in (await session.execute(stmt)).all():
            analysis = await analyze_offer(session, offer)
            if analysis:
                out.append(_deal_out(offer, product, analysis))
        return out

    @app.get("/deals")
    async def deals(min_score: int = 50, limit: int = 100, user: User = Depends(current_user), session=Depends(db)):
        rows = [d for d in await _analyzed(session, limit) if d["deal_score"] >= min_score]
        return sorted(rows, key=lambda d: d["deal_score"], reverse=True)

    @app.get("/deals/hot")
    async def hot_deals(limit: int = 100, user: User = Depends(current_user), session=Depends(db)):
        rows = [d for d in await _analyzed(session, limit) if d["deal_score"] >= 85]
        return sorted(rows, key=lambda d: d["deal_score"], reverse=True)

    @app.get("/deals/latest")
    async def latest_deals(limit: int = 50, user: User = Depends(current_user), session=Depends(db)):
        return await _analyzed(session, limit)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app
