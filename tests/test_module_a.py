import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from dealradar.core.security import hash_password, verify_password
from dealradar.models import Offer, Priority, Product, ProductVariant, Retailer, StockStatus
from dealradar.services.history import compute_metrics, record_snapshot
from dealradar.services.users import EmailTaken, authenticate, register_user
from dealradar.services.watchlist import add_watch, deactivate_watch, list_watches, watchers_of_product

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


async def make_offer(session, sku="123"):
    retailer = Retailer(code="jbhifi", name="JB Hi-Fi", domain="jbhifi.com.au")
    product = Product(brand="Sony", model="WH-1000XM6", name="Sony WH-1000XM6 Black")
    session.add_all([retailer, product])
    await session.flush()
    offer = Offer(product_id=product.id, retailer_id=retailer.id, retailer_sku=sku, url="https://www.jbhifi.com.au/x", title="t")
    session.add(offer)
    await session.flush()
    return product, offer


def test_password_hash_roundtrip():
    h = hash_password("secret")
    assert h != "secret" and verify_password("secret", h)
    assert not verify_password("wrong", h)
    assert not verify_password("secret", "garbage")


async def test_register_and_authenticate(session):
    user = await register_user(session, " A@Example.com ", "pw12345678", "Wayne")
    assert user.email == "a@example.com" and user.preferences.currency == "AUD"
    assert await authenticate(session, "a@example.com", "pw12345678") is not None
    assert await authenticate(session, "a@example.com", "bad") is None
    assert await authenticate(session, "nobody@example.com", "pw12345678") is None


async def test_duplicate_email_rejected(session):
    await register_user(session, "a@example.com", "pw")
    with pytest.raises(EmailTaken):
        await register_user(session, "A@example.com", "pw")


async def test_offer_is_separate_from_product_and_unique_per_retailer_sku(session):
    product, offer = await make_offer(session)
    session.add(ProductVariant(product_id=product.id, colour="Black", variant_key="sony-wh1000xm6-black"))
    await session.flush()
    dup = Offer(product_id=product.id, retailer_id=offer.retailer_id, retailer_sku="123", url="u", title="t")
    session.add(dup)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_metrics_windows_and_flagged_excluded(session):
    _, offer = await make_offer(session)
    rec = lambda price, days, **kw: record_snapshot(
        session, offer.id, Decimal(price), timestamp=NOW - timedelta(days=days), **kw
    )
    await rec("600", 100)  # outside 90d, still all-time
    await rec("500", 60)
    await rec("450", 20)
    await rec("19.99", 10, flagged=True)  # suspicious, must be ignored
    await rec("420", 3, stock_status=StockStatus.IN_STOCK)

    m = await compute_metrics(session, offer.id, now=NOW)
    assert m.current == Decimal("420")
    assert m.low_7d == Decimal("420")
    assert m.low_30d == Decimal("420") and m.avg_30d == Decimal("435.00")
    assert m.low_90d == Decimal("420") and m.avg_90d == Decimal("456.67")
    assert m.all_time_low == Decimal("420")
    assert m.volatility > 0


async def test_metrics_empty(session):
    _, offer = await make_offer(session)
    m = await compute_metrics(session, offer.id, now=NOW)
    assert m.current is None and m.all_time_low is None and m.volatility == 0.0


async def test_watchlist_upsert_list_and_deactivate(session):
    user = await register_user(session, "u@example.com", "pw")
    product, _ = await make_offer(session)
    w1 = await add_watch(session, user.id, product.id, target_price=Decimal("400"), priority=Priority.HIGH)
    w2 = await add_watch(session, user.id, product.id, target_price=Decimal("380"), notify_on_stock=True)
    assert w1.id == w2.id and w2.target_price == Decimal("380") and w2.priority == Priority.NORMAL
    assert len(await list_watches(session, user.id)) == 1
    assert len(await watchers_of_product(session, product.id)) == 1
    assert await deactivate_watch(session, user.id, w1.id)
    assert await list_watches(session, user.id) == []
    assert not await deactivate_watch(session, uuid.uuid4(), w1.id)
