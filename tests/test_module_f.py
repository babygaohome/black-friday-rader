import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.api.app import create_app
from dealradar.core.config import Settings
from dealradar.core.security import issue_token, verify_token
from dealradar.models import Alert, Offer, Priority, RetailerHealth
from dealradar.retailers.registry import RetailerRegistry
from dealradar.runtime import Runtime, build_runtime, find_due, retry_notifications, run_scan
from dealradar.scanning.dispatcher import due_scans
from dealradar.scanning.locks import MemoryLock
from retailers.jbhifi.adapter import JBHiFiAdapter

FIX = Path(__file__).parent.parent / "retailers" / "jbhifi" / "fixtures"
URL = "https://www.jbhifi.com.au/products/sony-wh1000xm6"


class Site:
    """Fake jbhifi.com.au: serves a fixture page, switchable between scans."""

    def __init__(self, page="jbhifi_product_normal.html"):
        self.page = page

    async def __call__(self, url):
        return httpx.Response(200, text=(FIX / self.page).read_text(), request=httpx.Request("GET", url))


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def __call__(self, method, payload):
        self.sent.append(payload)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def site():
    return Site()


@pytest.fixture
def registry(site):
    r = RetailerRegistry()
    r.register(JBHiFiAdapter(fetcher=site))
    return r


@pytest.fixture
async def client(factory, registry):
    app = create_app(factory, registry, secret_key="test-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def signup(client, email="a@example.com"):
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- tokens / auth ----------
def test_token_roundtrip_expiry_and_tamper():
    t = issue_token("s", "user-1", 60, now=1000)
    assert verify_token("s", t, now=1030) == "user-1"
    assert verify_token("s", t, now=1100) is None
    assert verify_token("other", t, now=1030) is None
    assert verify_token("s", t.replace("user-1", "user-2"), now=1030) is None
    assert verify_token("s", "garbage") is None


async def test_auth_flow(client):
    h = await signup(client)
    assert (await client.get("/users/me", headers=h)).json()["email"] == "a@example.com"
    assert (await client.post("/auth/register", json={"email": "A@example.com", "password": "password123"})).status_code == 409
    assert (await client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpass1"})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})).status_code == 200
    assert (await client.get("/users/me")).status_code == 401
    assert (await client.get("/users/me", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.post("/auth/register", json={"email": "bad", "password": "password123"})).status_code == 422
    assert (await client.post("/auth/register", json={"email": "b@example.com", "password": "short"})).status_code == 422


# ---------- products from URL ----------
async def test_add_product_from_url_and_idempotent(client):
    h = await signup(client)
    r = await client.post("/products/from-url", json={"url": URL}, headers=h)
    assert r.status_code == 201 and r.json()["created"] is True
    pid = r.json()["product_id"]
    again = await client.post("/products/from-url", json={"url": URL}, headers=h)
    assert again.json()["created"] is False and again.json()["product_id"] == pid

    offers = (await client.get(f"/products/{pid}/offers", headers=h)).json()
    assert offers[0]["retailer"] == "jbhifi" and Decimal(str(offers[0]["effective_price"])) == Decimal("549")
    detail = (await client.get(f"/products/{pid}", headers=h)).json()
    assert detail["name"].startswith("Sony WH-1000XM6") and len((await client.get(f"/products/{pid}/history", headers=h)).json()) == 1
    assert len((await client.get("/products?q=xm6", headers=h)).json()) == 1


async def test_from_url_rejects_non_allowlisted_and_requires_auth(client):
    h = await signup(client)
    for bad in ["https://evil.com/p", "http://www.jbhifi.com.au/p", "https://127.0.0.1/x", "ftp://x"]:
        assert (await client.post("/products/from-url", json={"url": bad}, headers=h)).status_code == 422
    assert (await client.post("/products/from-url", json={"url": URL})).status_code == 401


async def test_from_url_scan_error_is_502(factory):
    async def blocked(url):
        return httpx.Response(429, request=httpx.Request("GET", url))

    reg = RetailerRegistry()
    reg.register(JBHiFiAdapter(fetcher=blocked))
    app = create_app(factory, reg, "s")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        h = await signup(c)
        r = await c.post("/products/from-url", json={"url": URL}, headers=h)
    assert r.status_code == 502 and "RATE_LIMIT" in r.json()["detail"]


async def test_retailers_listing_is_pluggable(client):
    h = await signup(client)
    assert [r["code"] for r in (await client.get("/retailers", headers=h)).json()] == ["jbhifi"]


# ---------- watchlist ----------
async def test_watchlist_crud_and_isolation(client):
    h1, h2 = await signup(client, "a@example.com"), await signup(client, "b@example.com")
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=h1)).json()["product_id"]
    w = (await client.post("/watchlist", json={"product_id": pid, "target_price": "400", "priority": "HIGH"}, headers=h1)).json()
    assert w["priority"] == "HIGH" and Decimal(str(w["target_price"])) == 400
    assert len((await client.get("/watchlist", headers=h1)).json()) == 1
    assert (await client.get("/watchlist", headers=h2)).json() == []
    assert (await client.patch(f"/watchlist/{w['id']}", json={"target_price": "380"}, headers=h2)).status_code == 404
    assert (await client.delete(f"/watchlist/{w['id']}", headers=h2)).status_code == 404
    patched = (await client.patch(f"/watchlist/{w['id']}", json={"target_price": "380", "notify_on_stock": True}, headers=h1)).json()
    assert Decimal(str(patched["target_price"])) == 380 and patched["notify_on_stock"] is True
    assert (await client.delete(f"/watchlist/{w['id']}", headers=h1)).status_code == 204
    assert (await client.get("/watchlist", headers=h1)).json() == []
    assert (await client.post("/watchlist", json={"product_id": str(uuid.uuid4())}, headers=h1)).status_code == 404
    assert (await client.post("/watchlist", json={"product_id": pid, "target_price": "-5"}, headers=h1)).status_code == 422


# ---------- dispatcher ----------
async def test_due_scans_priority_interval_and_health(factory, client):
    h = await signup(client)
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=h)).json()["product_id"]
    async with factory() as s:
        assert await due_scans(s) == []  # nobody watches it yet
    await client.post("/watchlist", json={"product_id": pid, "priority": "HIGH"}, headers=h)

    now = datetime.now(timezone.utc)
    async with factory() as s:
        [d] = await due_scans(s, now)  # never scanned
        assert d.priority == Priority.HIGH and d.queue == "scan.high"
        offer = await s.get(Offer, d.offer_id)
        offer.last_scanned_at = now - timedelta(seconds=60)
        await s.commit()
        assert await due_scans(s, now) == []  # HIGH = 2min
        assert len(await due_scans(s, now + timedelta(seconds=61))) == 1
        s.add(RetailerHealth(retailer_id=offer.retailer_id, success_rate=Decimal("0.5"), status="DEGRADED"))
        await s.commit()
        assert await due_scans(s, now + timedelta(seconds=130)) == []  # degraded retailer is scanned less often
        assert len(await due_scans(s, now + timedelta(seconds=400), event_mode="BLACK_FRIDAY")) == 1  # event mode halves it
        assert len(await due_scans(s, now + timedelta(seconds=800))) == 1  # 120s x 2 (degraded) x 3 (50% success) = 720s


# ---------- full loop: URL -> watch -> scan -> price drop -> alert -> Telegram ----------
async def test_full_closed_loop(factory, registry, site, client):
    h = await signup(client)
    await client.patch("/users/me", json={"telegram_chat_id": "42"}, headers=h)
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=h)).json()["product_id"]
    await client.post("/watchlist", json={"product_id": pid, "target_price": "400"}, headers=h)

    tg = FakeTelegram()
    rt = build_runtime(Settings(telegram_bot_token="x", database_url="sqlite+aiosqlite:///:memory:"),
                       lock=MemoryLock(), cooldown=MemoryCooldown(), registry=registry, notifier_transport=tg,
                       session_factory=factory)

    [due] = await find_due(rt)
    site.page = "jbhifi_sale.html"  # price drops to 399
    result = await run_scan(rt, due.offer_id)
    assert result.status == "OK" and result.price_changed

    alerts = (await client.get("/alerts", headers=h)).json()
    assert [a["type"] for a in alerts] == ["TARGET_PRICE_HIT"] and Decimal(str(alerts[0]["price"])) == 399
    assert len(tg.sent) == 1 and tg.sent[0]["chat_id"] == "42" and "A$399" in tg.sent[0]["text"]
    assert (await client.post(f"/alerts/{alerts[0]['id']}/read", headers=h)).status_code == 204
    assert (await client.get("/alerts", headers=h)).json()[0]["read"] is True
    assert await find_due(rt) == []  # just scanned, not due again

    assert await retry_notifications(rt) == 0
    assert await run_scan(rt, uuid.uuid4()) is None  # unknown offer is ignored
