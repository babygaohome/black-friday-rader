from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.alerts.engine import AlertEngine
from dealradar.events import EventBus, PriceChanged, StockChanged
from dealradar.models import (
    Alert, AlertType, Notification, NotificationStatus, Offer, Priority, Product, Retailer, StockStatus,
)
from dealradar.notifications.telegram import TelegramNotifier, format_alert
from dealradar.retailers.base import RawOffer, RetailerAdapter
from dealradar.scanning.locks import MemoryLock
from dealradar.scanning.scanner import scan_offer
from dealradar.services.history import record_snapshot
from dealradar.services.users import register_user
from dealradar.services.watchlist import add_watch


class Scripted(RetailerAdapter):
    code, name, domains = "jbhifi", "JB Hi-Fi", ("jbhifi.com.au",)

    def __init__(self, *items):
        self.items = list(items)

    async def fetch_product(self, url):
        return self.items.pop(0)


def raw(price, avail="In stock"):
    return RawOffer("jbhifi", "1", "Sony WH-1000XM6", "https://www.jbhifi.com.au/p", price, "549", availability=avail)


async def setup(session, chat_id="999", **watch):
    user = await register_user(session, "u@example.com", "pw")
    user.preferences.telegram_chat_id = chat_id
    retailer = Retailer(code="jbhifi", name="JB Hi-Fi", domain="jbhifi.com.au")
    product = Product(brand="Sony", model="WH-1000XM6", name="Sony WH-1000XM6")
    session.add_all([retailer, product])
    await session.flush()
    offer = Offer(product_id=product.id, retailer_id=retailer.id, retailer_sku="1", url="https://www.jbhifi.com.au/p", title="t")
    session.add(offer)
    await add_watch(session, user.id, product.id, **watch)
    await session.commit()
    return user, product, offer


class FakeTelegram:
    def __init__(self, status=200):
        self.sent, self.status = [], status

    async def __call__(self, method, payload):
        self.sent.append((method, payload))
        return httpx.Response(self.status, json={"ok": self.status == 200})


def far_apart_clock():
    """Each cooldown check happens an hour after the previous one, so cooldowns never block."""
    t = [0.0]

    def clock():
        t[0] += 3600
        return t[0]

    return clock


def wire(factory, tg=None, cooldown=None):
    notifier = TelegramNotifier("T", transport=tg) if tg else None
    engine = AlertEngine(factory, cooldown or MemoryCooldown(), notifier)
    bus = EventBus()
    engine.register(bus)
    return engine, bus


async def alerts(session):
    return (await session.execute(select(Alert).order_by(Alert.created_at).execution_options(populate_existing=True))).scalars().all()


async def test_target_price_hit_end_to_end_sends_telegram(factory, session):
    user, product, offer = await setup(session, target_price=Decimal("400"))
    tg = FakeTelegram()
    _, bus = wire(factory, tg)
    adapter = Scripted(raw("449"), raw("399"))
    await scan_offer(session, offer, adapter, MemoryLock(), bus)
    assert await alerts(session) == []  # 449 > 400
    await scan_offer(session, offer, adapter, MemoryLock(), bus)

    [a] = await alerts(session)
    assert a.type == AlertType.TARGET_PRICE_HIT and a.price == Decimal("399.00") and a.previous_price == Decimal("449.00")
    assert len(tg.sent) == 1
    method, payload = tg.sent[0]
    assert method == "sendMessage" and payload["chat_id"] == "999"
    assert "A$449 → <b>A$399</b>" in payload["text"] and "JB Hi-Fi" in payload["text"]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "VIEW DEAL"
    [n] = (await session.execute(select(Notification))).scalars().all()
    assert n.status == NotificationStatus.SENT and n.sent_at is not None


async def test_cooldown_dedupes_flapping_prices(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("430"))
    _, bus = wire(factory, FakeTelegram())
    adapter = Scripted(raw("449"), raw("419"), raw("420"), raw("418"), raw("419"), raw("417"))
    for _ in range(6):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    assert len(await alerts(session)) == 1  # 419 -> 417 are further drops but inside the cooldown


async def test_price_increase_never_alerts(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("500"))
    _, bus = wire(factory)
    adapter = Scripted(raw("600"), raw("550"), raw("560"))
    for _ in range(3):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    assert await alerts(session) == []


async def test_out_of_stock_price_hit_does_not_alert(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("500"))
    _, bus = wire(factory)
    await scan_offer(session, offer, Scripted(raw("449", "Out of stock")), MemoryLock(), bus)
    assert await alerts(session) == []


async def test_restock_alert_only_when_opted_in(factory, session):
    user, product, offer = await setup(session, notify_on_stock=True)
    tg = FakeTelegram()
    _, bus = wire(factory, tg)
    adapter = Scripted(raw("449", "Out of stock"), raw("449", "In stock"))
    await scan_offer(session, offer, adapter, MemoryLock(), bus)
    await scan_offer(session, offer, adapter, MemoryLock(), bus)
    [a] = await alerts(session)
    assert a.type == AlertType.RESTOCK and "BACK IN STOCK" in tg.sent[0][1]["text"]


async def test_restock_not_sent_without_opt_in(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("1"))
    _, bus = wire(factory)
    adapter = Scripted(raw("449", "Out of stock"), raw("449", "In stock"))
    for _ in range(2):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    assert await alerts(session) == []


async def test_historical_low(factory, session):
    _, _, offer = await setup(session, notify_on_historical_low=True)
    _, bus = wire(factory, cooldown=MemoryCooldown(far_apart_clock()))
    adapter = Scripted(raw("500"), raw("450"), raw("470"), raw("440"))
    for _ in range(4):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    got = await alerts(session)
    assert [a.price for a in got] == [Decimal("450.00"), Decimal("440.00")]  # 470 is a rise: no alert
    assert all(a.type == AlertType.HISTORICAL_LOW for a in got)


async def test_minimum_discount_uses_30d_average(factory, session):
    _, _, offer = await setup(session, minimum_discount=Decimal("20"))
    _, bus = wire(factory)
    adapter = Scripted(raw("500"), raw("500"), raw("490"), raw("380"))
    for _ in range(4):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    [a] = await alerts(session)
    assert a.type == AlertType.PRICE_DROP and a.price == Decimal("380.00")  # avg ~496.7 -> 23% off; 490 was only ~1%


async def test_flagged_price_never_alerts(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("100"))
    _, bus = wire(factory)
    adapter = Scripted(*[raw("1999")] * 3, raw("19.99"))
    for _ in range(4):
        await scan_offer(session, offer, adapter, MemoryLock(), bus)
    assert await alerts(session) == []


async def test_no_telegram_chat_means_alert_but_no_notification(factory, session):
    _, _, offer = await setup(session, chat_id=None, target_price=Decimal("500"))
    tg = FakeTelegram()
    _, bus = wire(factory, tg)
    await scan_offer(session, offer, Scripted(raw("449")), MemoryLock(), bus)
    assert len(await alerts(session)) == 1 and tg.sent == []
    assert (await session.execute(select(Notification))).scalars().all() == []


async def test_telegram_failure_retries_then_fails(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("500"))
    tg = FakeTelegram(status=500)
    notifier = TelegramNotifier("T", transport=tg)
    _, bus = wire(factory, tg)
    await scan_offer(session, offer, Scripted(raw("449")), MemoryLock(), bus)
    session.expire_all()
    [n] = (await session.execute(select(Notification))).scalars().all()
    assert n.status == NotificationStatus.RETRY and n.retry_count == 1 and n.error == "HTTP 500"
    await notifier.deliver(session, n.id)
    assert (await notifier.deliver(session, n.id)) == NotificationStatus.FAILED
    assert n.retry_count == 3


async def test_telegram_400_is_not_retried(factory, session):
    _, _, offer = await setup(session, target_price=Decimal("500"))
    _, bus = wire(factory, FakeTelegram(status=400))
    await scan_offer(session, offer, Scripted(raw("449")), MemoryLock(), bus)
    session.expire_all()
    [n] = (await session.execute(select(Notification))).scalars().all()
    assert n.status == NotificationStatus.FAILED


def test_format_escapes_html_and_shows_restock_without_arrow():
    a = Alert(type=AlertType.RESTOCK, price=Decimal("449"), previous_price=None, deal_score=None)
    p = format_alert(a, "Sony <b>XM6</b>", "JB & Co", "IN_STOCK", "https://www.jbhifi.com.au/p")
    assert "&lt;b&gt;" in p["text"] and "JB &amp; Co" in p["text"] and "→" not in p["text"]
