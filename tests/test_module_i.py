from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.alerts.engine import AlertEngine
from dealradar.api.app import create_app
from dealradar.deal.fake import assess_discount
from dealradar.deal.score import DealInput, grade, score_deal
from dealradar.events import EventBus
from dealradar.models import Alert, Offer, Product, Retailer, StockStatus
from dealradar.notifications.telegram import TelegramNotifier
from dealradar.retailers.base import RawOffer, RetailerAdapter
from dealradar.retailers.registry import RetailerRegistry
from dealradar.scanning.locks import MemoryLock
from dealradar.scanning.scanner import scan_offer
from dealradar.services.deals import analyze_offer
from dealradar.services.history import prior_stats, record_snapshot
from dealradar.services.users import register_user
from dealradar.services.watchlist import add_watch

D = Decimal
NOW = datetime.now(timezone.utc)


# ---------- fake discount detection ----------
def test_design_doc_fake_discount_example():
    r = assess_discount(D("679"), D("999"), D("699"), history_points=30)
    assert r.retailer_discount_pct == 32.0 and r.actual_discount_pct == 2.9
    assert r.verdict == "MISLEADING" and r.normal_price == D("699")


def test_genuine_discount_and_no_claim_and_unverified():
    assert assess_discount(D("399"), D("549"), D("499"), 30).verdict == "GENUINE"  # 27% claimed, 20% real
    assert assess_discount(D("399"), None, D("499"), 30).verdict == "NO_CLAIM"
    assert assess_discount(D("399"), D("399"), D("499"), 30).verdict == "NO_CLAIM"
    r = assess_discount(D("399"), D("549"), D("499"), history_points=2)
    assert r.verdict == "UNVERIFIED" and r.actual_discount_pct is None and r.normal_price is None


def test_small_claims_are_not_flagged():
    assert assess_discount(D("95"), D("100"), D("100"), 30).verdict == "GENUINE"  # 5% claim: below the 10% floor


# ---------- score ----------
def inp(price, **kw):
    base = dict(price=D(price), stock=StockStatus.IN_STOCK, report=assess_discount(D(price), D("549"), D("529"), 30),
                avg_30d=D("529"), avg_90d=D("520"), all_time_low=D("449"), history_points=30)
    base.update(kw)
    return DealInput(**base)


def test_doc_example_scores_very_high():
    # price 419; 30d avg 529; all-time low 449 (so a new low): the doc's "94" example class
    s = score_deal(inp("419", recent_drop_pct=8))
    assert s.verified and s.new_all_time_low and s.score >= 90 and s.grade in ("VERY_GOOD", "EXTREME")


def test_grades_boundaries():
    assert [grade(x) for x in (100, 95, 94, 85, 84, 70, 69, 50, 49, 0)] == [
        "EXTREME", "EXTREME", "VERY_GOOD", "VERY_GOOD", "GOOD", "GOOD", "NORMAL", "NORMAL", "IGNORE", "IGNORE"]


def test_normal_price_scores_low_and_better_price_scores_higher():
    ordinary = score_deal(inp("529", report=assess_discount(D("529"), D("549"), D("529"), 30)))
    sale = score_deal(inp("439"))
    assert ordinary.score < 50 and sale.score > ordinary.score


def test_no_history_is_capped_and_unverified():
    s = score_deal(DealInput(price=D("100"), stock=StockStatus.IN_STOCK, report=assess_discount(D("100"), D("300"), None, 0),
                             history_points=0, seller_confidence=1.0, recent_drop_pct=50))
    assert not s.verified and s.score <= 69 and s.grade != "VERY_GOOD"


def test_misleading_discount_is_penalised_and_out_of_stock_is_not_a_deal():
    real = score_deal(inp("679", report=assess_discount(D("679"), D("999"), D("849"), 30), avg_30d=D("849"), avg_90d=D("849"),
                          all_time_low=D("649")))
    fake = score_deal(inp("679", report=assess_discount(D("679"), D("999"), D("699"), 30), avg_30d=D("699"), avg_90d=D("699"),
                          all_time_low=D("649")))
    assert assess_discount(D("679"), D("999"), D("849"), 30).verdict == "GENUINE"
    assert fake.components["current_discount"] < real.components["current_discount"]
    oos = score_deal(inp("419", stock=StockStatus.OUT_OF_STOCK))
    assert oos.score <= 49 and oos.grade == "IGNORE"


def test_score_is_clamped():
    s = score_deal(inp("1", recent_drop_pct=99, seller_confidence=5.0))
    assert 0 <= s.score <= 100


# ---------- prior stats / analysis (DB) ----------
class Scripted(RetailerAdapter):
    code, name, domains = "jbhifi", "JB Hi-Fi", ("jbhifi.com.au",)

    def __init__(self, *items):
        self.items = list(items)

    async def fetch_product(self, url):
        return self.items.pop(0)


def raw(price, original="549", avail="In stock"):
    return RawOffer("jbhifi", "1", "Sony WH-1000XM6", "https://www.jbhifi.com.au/p", price, original, availability=avail)


async def make_offer(session):
    r = Retailer(code="jbhifi", name="JB Hi-Fi", domain="jbhifi.com.au")
    p = Product(brand="Sony", name="Sony WH-1000XM6")
    session.add_all([r, p])
    await session.flush()
    o = Offer(product_id=p.id, retailer_id=r.id, retailer_sku="1", url="https://www.jbhifi.com.au/p", title="t")
    session.add(o)
    await session.flush()
    return p, o


async def seed_history(session, offer, prices, start_days_ago=30):
    for i, price in enumerate(prices):
        await record_snapshot(session, offer.id, D(price), original_price=D("549"), stock_status=StockStatus.IN_STOCK,
                              timestamp=NOW - timedelta(days=start_days_ago - i))
    offer.current_effective_price, offer.original_price = D(prices[-1]), D("549")
    offer.stock_status = StockStatus.IN_STOCK
    await session.flush()


async def test_prior_stats_exclude_the_newest_point(session):
    _, offer = await make_offer(session)
    await seed_history(session, offer, ["500", "500", "500", "400"], start_days_ago=10)
    st = await prior_stats(session, offer.id, NOW)
    assert (st.count, st.avg_30d, st.all_time_low, st.latest, st.previous) == (3, D("500.00"), D("500"), D("400"), D("500"))


async def test_analyze_offer_end_to_end(session):
    _, offer = await make_offer(session)
    assert await analyze_offer(session, offer) is None  # no price yet
    await seed_history(session, offer, ["529"] * 20 + ["429"], start_days_ago=20)
    a = await analyze_offer(session, offer, NOW)
    assert a.score.new_all_time_low and a.score.verified and a.score.score >= 80
    assert a.discount.verdict == "GENUINE" and a.discount.actual_discount_pct == 18.9


async def test_fake_discount_detected_from_history(session):
    _, offer = await make_offer(session)
    offer.original_price = D("999")
    await seed_history(session, offer, ["699"] * 20 + ["679"], start_days_ago=20)
    offer.original_price = D("999")
    a = await analyze_offer(session, offer, NOW)
    assert a.discount.verdict == "MISLEADING" and a.discount.retailer_discount_pct == 32.0
    assert a.discount.actual_discount_pct == 2.9


# ---------- alerts carry the score ----------
class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def __call__(self, method, payload):
        self.sent.append(payload)
        return httpx.Response(200, json={"ok": True})


async def test_alert_has_score_and_message_shows_real_discount(factory, session):
    user = await register_user(session, "u@example.com", "pw")
    user.preferences.telegram_chat_id = "7"
    product, offer = await make_offer(session)
    await add_watch(session, user.id, product.id, target_price=D("450"))
    await seed_history(session, offer, ["529"] * 10 + ["529"], start_days_ago=11)
    await session.commit()

    tg = FakeTelegram()
    bus = EventBus()
    AlertEngine(factory, MemoryCooldown(), TelegramNotifier("T", transport=tg)).register(bus)
    await scan_offer(session, offer, Scripted(raw("419")), MemoryLock(), bus)

    [alert] = (await session.execute(select(Alert).execution_options(populate_existing=True))).scalars().all()
    assert alert.deal_score is not None and alert.deal_score >= 70
    text = tg.sent[0]["text"]
    assert f"Deal Score: {alert.deal_score}" in text and "Retailer discount: 23.7%" in text and "Real vs 30-day price: 20.8%" in text
    assert "New all-time low" in text


# ---------- API ----------
async def test_deals_api_ranks_and_filters(factory):
    reg = RetailerRegistry()

    class Shop(RetailerAdapter):
        code, name, domains = "jbhifi", "JB Hi-Fi", ("jbhifi.com.au",)

        async def fetch_product(self, url):
            return raw("549", original=None)

    reg.register(Shop())
    app = create_app(factory, reg, "s")
    async with factory() as s:
        _, offer = await make_offer(s)
        await seed_history(s, offer, ["529"] * 20 + ["419"], start_days_ago=20)
        offer.last_scanned_at = datetime.now(timezone.utc)
        await s.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/auth/register", json={"email": "a@example.com", "password": "password123"})
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        assert (await c.get("/deals")).status_code == 401
        rows = (await c.get("/deals?min_score=50", headers=h)).json()
        assert len(rows) == 1 and rows[0]["retailer"] == "jbhifi" and rows[0]["discount_verdict"] in ("GENUINE", "UNVERIFIED")
        assert rows[0]["new_all_time_low"] is True and rows[0]["deal_score"] >= 70
        assert len((await c.get("/deals/latest", headers=h)).json()) == 1
        assert (await c.get("/deals?min_score=101", headers=h)).json() == []
        pid = rows[0]["product_id"]
        detail = (await c.get(f"/products/{pid}", headers=h)).json()
        assert detail["deal"]["deal_score"] == rows[0]["deal_score"]
