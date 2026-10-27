import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from dealradar.models import Alert, AlertType, MatchReview, Offer, Product, ProductVariant, ReviewStatus, WatchItem
from dealradar.retailers.base import RetailerAdapter
from dealradar.retailers.registry import RetailerRegistry
from dealradar.services.catalog import add_from_url
from dealradar.services.match_review import ReviewNotPending, confirm, list_pending, reject
from dealradar.services.users import register_user
from dealradar.services.watchlist import add_watch
from dealradar.retailers.base import RawOffer


class FakeShop(RetailerAdapter):
    def __init__(self, code, domain, pages):
        self.code, self.name, self.domains = code, code.title(), (domain,)
        self.pages = pages

    async def fetch_product(self, url):
        return self.pages[url]


def raw(code, sku, title, price, **kw):
    return RawOffer(code, sku, title, f"https://www.{code}.com.au/{sku}", price, "699", availability="In stock", **kw)


@pytest.fixture
def shops():
    pages_a = {
        "https://www.a.com.au/1": raw("a", "1", "Sony WH-1000XM6 Wireless Headphones Black", "449", brand="Sony", mpn="WH1000XM6B", gtin="4548736145871"),
        "https://www.a.com.au/2": raw("a", "2", "Apple iPhone 17 256GB Black", "1299", brand="Apple"),
    }
    pages_b = {
        "https://www.b.com.au/10": raw("b", "10", "Sony WH-1000XM6 Noise Cancelling Headphones - Black", "429", brand="Sony", mpn="WH1000XM6B", gtin="4548736145871"),
        "https://www.b.com.au/11": raw("b", "11", "Sony WH-1000XM6 Headphones Black (no ids)", "439", brand="Sony"),
        "https://www.b.com.au/12": raw("b", "12", "Apple iPhone 17 512GB Black", "1499", brand="Apple"),
        "https://www.b.com.au/13": raw("b", "13", "Apple iPhone 17 256GB Black", "1279", brand="Apple"),
        "https://www.b.com.au/14": raw("b", "14", "Sony XM6 Headphones Black", "419", brand="Sony"),
    }
    reg = RetailerRegistry()
    reg.register(FakeShop("a", "a.com.au", pages_a))
    reg.register(FakeShop("b", "b.com.au", pages_b))
    return reg


async def add(session, reg, url):
    r = await add_from_url(session, reg, url)
    await session.commit()
    return r


async def test_same_product_from_two_retailers_is_merged_by_gtin(session, shops):
    a = await add(session, shops, "https://www.a.com.au/1")
    b = await add(session, shops, "https://www.b.com.au/10")
    assert a.product.id == b.product.id and a.offer.id != b.offer.id
    assert b.offer.match_confidence == Decimal("1.0") and not b.needs_review


async def test_matched_by_title_without_identifiers(session, shops):
    a = await add(session, shops, "https://www.a.com.au/1")
    b = await add(session, shops, "https://www.b.com.au/11")
    assert a.product.id == b.product.id
    assert b.offer.match_confidence >= Decimal("0.85")


async def test_different_storage_is_a_separate_product_and_same_storage_merges(session, shops):
    a = await add(session, shops, "https://www.a.com.au/2")  # 256GB
    b512 = await add(session, shops, "https://www.b.com.au/12")
    b256 = await add(session, shops, "https://www.b.com.au/13")
    assert b512.product.id != a.product.id
    assert b256.product.id == a.product.id
    products = (await session.execute(select(Product).where(Product.brand == "Apple"))).scalars().all()
    assert len(products) == 2
    keys = {v.variant_key for v in (await session.execute(select(ProductVariant))).scalars()}
    assert any("256gb" in k for k in keys) and any("512gb" in k for k in keys)


async def test_low_confidence_creates_review_and_standin_product(session, shops):
    a = await add(session, shops, "https://www.a.com.au/1")
    b = await add(session, shops, "https://www.b.com.au/14")  # "Sony XM6" shorthand
    assert b.needs_review and b.product.id != a.product.id
    [review] = await list_pending(session)
    assert review.offer_id == b.offer.id and review.suggested_product_id == a.product.id
    assert review.product_id == b.product.id and review.method == "FUZZY"


async def test_confirm_moves_offer_and_watchers_and_removes_standin(session, shops):
    a = await add(session, shops, "https://www.a.com.au/1")
    b = await add(session, shops, "https://www.b.com.au/14")
    alice = await register_user(session, "alice@example.com", "password123")
    bob = await register_user(session, "bob@example.com", "password123")
    await add_watch(session, alice.id, b.product.id, target_price=Decimal("400"))  # watching the stand-in
    await add_watch(session, bob.id, b.product.id)
    await add_watch(session, bob.id, a.product.id)  # bob already watches the target
    alert = Alert(type=AlertType.PRICE_DROP, user_id=alice.id, product_id=b.product.id, offer_id=b.offer.id, price=Decimal("399"))
    session.add(alert)
    await session.commit()
    [review] = await list_pending(session)
    standin_id = b.product.id

    target = await confirm(session, review.id)
    await session.commit()
    assert target.id == a.product.id
    offer = await session.get(Offer, b.offer.id)
    assert offer.product_id == a.product.id and offer.match_confidence == 1
    assert await session.get(Product, standin_id) is None
    assert (await session.get(Alert, alert.id)).product_id == a.product.id  # history follows the offer
    # the resolved review must not keep pointing at the deleted stand-in (a foreign-key error on PostgreSQL)
    resolved = await session.get(MatchReview, review.id)
    assert resolved.product_id == a.product.id and resolved.suggested_product_id == a.product.id
    watchers = (await session.execute(select(WatchItem.user_id).where(WatchItem.product_id == a.product.id))).scalars().all()
    assert sorted(map(str, watchers)) == sorted(map(str, [alice.id, bob.id]))  # no duplicate for bob
    assert await list_pending(session) == []
    with pytest.raises(ReviewNotPending):
        await confirm(session, review.id)


async def test_reject_keeps_separate_product(session, shops):
    await add(session, shops, "https://www.a.com.au/1")
    b = await add(session, shops, "https://www.b.com.au/14")
    [review] = await list_pending(session)
    await reject(session, review.id)
    await session.commit()
    assert (await session.get(MatchReview, review.id)).status == ReviewStatus.REJECTED
    assert (await session.get(Offer, b.offer.id)).product_id == b.product.id
    with pytest.raises(ReviewNotPending):
        await reject(session, review.id)


async def test_readding_same_listing_is_idempotent(session, shops):
    first = await add(session, shops, "https://www.a.com.au/1")
    again = await add(session, shops, "https://www.a.com.au/1")
    assert not again.created and again.product.id == first.product.id
