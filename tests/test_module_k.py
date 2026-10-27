import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from dealradar.admin_ops import celery_worker_stats, redis_queue_stats
from dealradar.api.app import create_app
from dealradar.cli import set_admin
from dealradar.models import Offer, PriceHistory, Product, Retailer, RetailerHealth, ScanJob, StockStatus
from dealradar.retailers.registry import RetailerRegistry
from dealradar.scanning.queues import QUEUE_NAMES
from dealradar.services.catalog import add_from_url
from tests.test_module_h_catalog import FakeShop, raw


@pytest.fixture
def shops():
    a = {"https://www.a.com.au/1": raw("a", "1", "Sony WH-1000XM6 Wireless Headphones Black", "449", brand="Sony", mpn="WH1000XM6B", gtin="4548736145871")}
    b = {"https://www.b.com.au/14": raw("b", "14", "Sony XM6 Headphones Black", "419", brand="Sony")}
    reg = RetailerRegistry()
    reg.register(FakeShop("a", "a.com.au", a))
    reg.register(FakeShop("b", "b.com.au", b))
    return reg


class FakeQueues:
    async def __call__(self):
        return {"scan.high": 3, "scan.normal": 40}


async def client_for(factory, registry, **kw):
    app = create_app(factory, registry, secret_key="test-secret", **kw)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture
async def api(factory, shops):
    async with await client_for(factory, shops, queue_stats=FakeQueues()) as c:
        yield c


async def signup(client, email):
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
async def admin(api, factory):
    h = await signup(api, "root@example.com")
    assert await set_admin(factory, "root@example.com")
    return h


async def seed(factory, shops):
    """Two retailers, a pending match review, a failed + ok scan job each, one suspicious price."""
    async with factory() as s:
        a = await add_from_url(s, shops, "https://www.a.com.au/1")
        b = await add_from_url(s, shops, "https://www.b.com.au/14")
        await s.commit()
        now = datetime.now(timezone.utc)
        s.add_all([
            ScanJob(offer_id=b.offer.id, status="FAILED", error_type="CAPTCHA", started_at=now, finished_at=now),
            ScanJob(offer_id=b.offer.id, status="FAILED", error_type="CAPTCHA", started_at=now, finished_at=now),
            ScanJob(offer_id=b.offer.id, status="FAILED", error_type="HTTP_ERROR", started_at=now, finished_at=now),
            ScanJob(offer_id=a.offer.id, status="OK", started_at=now, finished_at=now),
            ScanJob(offer_id=a.offer.id, status="FAILED", error_type="CAPTCHA", started_at=now - timedelta(days=3), finished_at=now - timedelta(days=3)),
            PriceHistory(offer_id=a.offer.id, price=Decimal("5"), effective_price=Decimal("5"), stock_status=StockStatus.IN_STOCK, flagged=True),
            RetailerHealth(retailer_id=b.offer.retailer_id, success_rate=Decimal("0.4"), error_rate=Decimal("0.6"), status="OFFLINE"),
        ])
        await s.commit()
        return a, b


# ---------- access control ----------
async def test_admin_routes_need_admin_role(api, factory):
    routes = ["/admin/overview", "/admin/retailers", "/admin/queues", "/admin/workers", "/admin/jobs/failed",
              "/admin/scraper-errors", "/admin/prices/suspicious", "/admin/matching/reviews"]
    user = await signup(api, "user@example.com")
    for path in routes:
        assert (await api.get(path)).status_code == 401
        assert (await api.get(path, headers=user)).status_code == 403
    rid = uuid.uuid4()
    for action in ("confirm", "reject"):
        assert (await api.post(f"/admin/matching/reviews/{rid}/{action}", headers=user)).status_code == 403
    assert (await api.get("/users/me", headers=user)).json()["is_admin"] is False


async def test_admin_cannot_be_self_granted_through_the_api(api):
    r = await api.post("/auth/register", json={"email": "sneaky@example.com", "password": "password123", "is_admin": True})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert (await api.get("/admin/overview", headers=h)).status_code == 403
    assert (await api.patch("/users/me", json={"is_admin": True}, headers=h)).status_code in (200, 422)
    assert (await api.get("/admin/overview", headers=h)).status_code == 403


async def test_cli_grants_and_revokes_admin(api, factory):
    h = await signup(api, "boss@example.com")
    assert await set_admin(factory, " Boss@Example.com ")
    assert (await api.get("/admin/overview", headers=h)).status_code == 200
    assert await set_admin(factory, "boss@example.com", admin=False)
    assert (await api.get("/admin/overview", headers=h)).status_code == 403
    assert not await set_admin(factory, "nobody@example.com")


# ---------- dashboards ----------
async def test_overview_counts(api, admin, factory, shops):
    await seed(factory, shops)
    o = (await api.get("/admin/overview", headers=admin)).json()
    assert o["users"] == 1 and o["products"] == 2 and o["active_offers"] == 2 and o["pending_reviews"] == 1
    assert o["failed_jobs_24h"] == 3 and o["suspicious_prices_24h"] == 1 and o["last_scan_at"]


async def test_retailer_health_table(api, admin, factory, shops):
    await seed(factory, shops)
    rows = {r["code"]: r for r in (await api.get("/admin/retailers", headers=admin)).json()}
    assert set(rows) == {"a", "b"}
    assert rows["b"]["status"] == "OFFLINE" and rows["b"]["success_rate"] == 0.4 and rows["b"]["registered"] is True
    assert rows["b"]["scans_last_hour"] == 3 and rows["b"]["failed_last_hour"] == 3
    assert rows["a"]["status"] == "UNKNOWN" and rows["a"]["scans_last_hour"] == 1 and rows["a"]["failed_last_hour"] == 0
    assert rows["a"]["active_offers"] == 1


async def test_unregistered_retailer_is_flagged(api, admin, factory, shops):
    await seed(factory, shops)
    async with factory() as s:
        s.add(Retailer(code="amazon_au", name="Amazon AU", domain="amazon.com.au"))
        await s.commit()
    rows = {r["code"]: r for r in (await api.get("/admin/retailers", headers=admin)).json()}
    assert rows["amazon_au"]["registered"] is False and rows["amazon_au"]["active_offers"] == 0


async def test_failed_jobs_and_scraper_errors(api, admin, factory, shops):
    await seed(factory, shops)
    failed = (await api.get("/admin/jobs/failed", headers=admin)).json()
    assert len(failed) == 3 and {j["retailer"] for j in failed} == {"b"} and failed[0]["url"].startswith("https://www.b.com.au")
    assert len((await api.get("/admin/jobs/failed?limit=1", headers=admin)).json()) == 1
    assert len((await api.get("/admin/jobs/failed?hours=100", headers=admin)).json()) == 4  # includes the 3-day-old failure

    errors = (await api.get("/admin/scraper-errors", headers=admin)).json()
    assert [(e["retailer"], e["error_type"], e["count"]) for e in errors] == [("b", "CAPTCHA", 2), ("b", "HTTP_ERROR", 1)]
    assert (await api.get("/admin/jobs/failed?hours=0", headers=admin)).status_code == 422


async def test_suspicious_prices(api, admin, factory, shops):
    a, _ = await seed(factory, shops)
    [row] = (await api.get("/admin/prices/suspicious", headers=admin)).json()
    assert row["retailer"] == "a" and row["observed_price"] == 5 and row["current_price"] == 449


# ---------- infrastructure probes ----------
async def test_queue_lengths_and_availability(api, admin, factory, shops):
    assert (await api.get("/admin/queues", headers=admin)).json() == {"available": True, "queues": {"scan.high": 3, "scan.normal": 40}}
    async with await client_for(factory, shops) as bare:
        h = await signup(bare, "x@example.com")
        await set_admin(factory, "x@example.com")
        assert (await bare.get("/admin/queues", headers=h)).json() == {"available": False, "queues": {}}
        assert (await bare.get("/admin/workers", headers=h)).json() == {"available": False, "workers": []}


async def test_probe_failure_is_reported_not_raised(factory, shops):
    async def broken():
        raise ConnectionError("redis down")

    async with await client_for(factory, shops, queue_stats=broken, worker_stats=broken) as c:
        h = await signup(c, "x@example.com")
        await set_admin(factory, "x@example.com")
        assert (await c.get("/admin/queues", headers=h)).json()["available"] is False
        assert (await c.get("/admin/workers", headers=h)).json()["available"] is False


async def test_worker_list_comes_from_probe(factory, shops):
    async def workers():
        return [{"name": "w1", "online": True, "active_tasks": 2}]

    async with await client_for(factory, shops, worker_stats=workers) as c:
        h = await signup(c, "x@example.com")
        await set_admin(factory, "x@example.com")
        assert (await c.get("/admin/workers", headers=h)).json() == {
            "available": True, "workers": [{"name": "w1", "online": True, "active_tasks": 2}]}


async def test_redis_queue_stats_reads_every_queue():
    class R:
        async def llen(self, name):
            return len(name)

    stats = await redis_queue_stats(R())()
    assert set(stats) == set(QUEUE_NAMES) and stats["scan.high"] == len("scan.high")


async def test_celery_worker_stats_uses_inspect_ping_and_active():
    class Inspector:
        def ping(self):
            return {"celery@b": {"ok": "pong"}, "celery@a": {"ok": "pong"}}

        def active(self):
            return {"celery@a": [{"id": 1}, {"id": 2}]}

    class App:
        class control:
            @staticmethod
            def inspect(timeout):
                assert timeout == 1.0
                return Inspector()

    assert await celery_worker_stats(App)() == [
        {"name": "celery@a", "online": True, "active_tasks": 2},
        {"name": "celery@b", "online": True, "active_tasks": 0},
    ]

    class Silent:
        class control:
            @staticmethod
            def inspect(timeout):
                class I:
                    ping = active = staticmethod(lambda: None)  # no worker answered
                return I()

    assert await celery_worker_stats(Silent)() == []


# ---------- matching review ----------
async def test_review_list_confirm_and_reject(api, admin, factory, shops):
    a, b = await seed(factory, shops)
    [review] = (await api.get("/admin/matching/reviews", headers=admin)).json()
    assert review["offer"]["retailer"] == "b" and review["suggested_product"]["id"] == str(a.product.id)
    assert 0 < review["confidence"] < 0.85 and review["method"] == "FUZZY"

    r = await api.post(f"/admin/matching/reviews/{review['id']}/confirm", headers=admin)
    assert r.status_code == 200 and r.json() == {"status": "CONFIRMED", "product_id": str(a.product.id)}
    async with factory() as s:
        assert (await s.get(Offer, b.offer.id)).product_id == a.product.id
        assert await s.get(Product, b.product.id) is None  # stand-in product removed
    assert (await api.get("/admin/matching/reviews", headers=admin)).json() == []
    assert (await api.post(f"/admin/matching/reviews/{review['id']}/confirm", headers=admin)).status_code == 404  # already resolved


async def test_reject_keeps_offer_on_its_own_product(api, admin, factory, shops):
    a, b = await seed(factory, shops)
    [review] = (await api.get("/admin/matching/reviews", headers=admin)).json()
    r = await api.post(f"/admin/matching/reviews/{review['id']}/reject", headers=admin)
    assert r.json() == {"status": "REJECTED", "product_id": str(b.product.id)}
    async with factory() as s:
        assert (await s.get(Offer, b.offer.id)).product_id == b.product.id
    assert (await api.get("/admin/matching/reviews", headers=admin)).json() == []
    assert (await api.post(f"/admin/matching/reviews/{uuid.uuid4()}/reject", headers=admin)).status_code == 404
