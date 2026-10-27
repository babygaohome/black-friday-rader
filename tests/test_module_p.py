import pytest

from dealradar.normalization.category import CATEGORIES, classify
from dealradar.retailers.registry import RetailerRegistry
from dealradar.services.catalog import add_from_url
from tests.test_module_h_catalog import FakeShop, raw
from tests.test_module_k import client_for, signup


@pytest.mark.parametrize("name,brand,expected", [
    ("Sony WH-1000XM6 Wireless Noise Cancelling Headphones", "Sony", "audio"),
    ("Apple iPhone 16 Pro 256GB Black Titanium", "Apple", "phones"),
    ("Apple iPad Air 11-inch M2 128GB", "Apple", "tablets"),
    ("Apple MacBook Air 13-inch M3", "Apple", "laptops"),
    ("Samsung 65 inch QN90D Neo QLED 4K Smart TV", "Samsung", "tv"),
    ("Sony PlayStation 5 Console", "Sony", "gaming"),
    ("Apple Watch Series 10 GPS 42mm", "Apple", "wearables"),
    ("Dyson V15 Detect Cordless Vacuum", "Dyson", "appliances"),
    ("Samsung 990 Pro 2TB NVMe SSD", "Samsung", "storage"),
    ("TP-Link Deco X55 Mesh WiFi System", "TP-Link", "networking"),
    ("Garden Hose 30m", "", "other"),
])
def test_classify(name, brand, expected):
    assert classify(name, brand) == expected
    assert expected in CATEGORIES


@pytest.fixture
def shops():
    items = {
        "https://www.a.com.au/1": raw("a", "1", "Sony WH-1000XM6 Wireless Headphones Black", "449", brand="Sony", mpn="WH1000XM6B"),
        "https://www.a.com.au/2": raw("a", "2", "Apple iPhone 16 128GB Black", "1399", brand="Apple"),
        "https://www.a.com.au/3": raw("a", "3", "Samsung 65 inch Neo QLED 4K Smart TV", "1999", brand="Samsung"),
    }
    reg = RetailerRegistry()
    reg.register(FakeShop("a", "a.com.au", items))
    return reg


async def test_search_and_categories(factory, shops):
    async with factory() as s:
        for n in (1, 2, 3):
            await add_from_url(s, shops, f"https://www.a.com.au/{n}")
        await s.commit()
    async with await client_for(factory, shops) as c:
        h = await signup(c, "u@example.com")
        assert (await c.get("/products", headers={})).status_code == 401

        everything = (await c.get("/products", headers=h)).json()
        assert {p["category"] for p in everything} == {"audio", "phones", "tv"}
        assert all(p["offer_count"] == 1 and p["best_price"] is not None for p in everything)

        # every word must match; name, brand and case are all searched
        assert [p["name"] for p in (await c.get("/products?q=sony headphones", headers=h)).json()] == [
            "Sony WH-1000XM6 Wireless Headphones Black"]
        assert len((await c.get("/products?q=APPLE", headers=h)).json()) == 1
        assert (await c.get("/products?q=sony iphone", headers=h)).json() == []

        tv = (await c.get("/products?category=tv", headers=h)).json()
        assert [p["category"] for p in tv] == ["tv"]
        assert (await c.get("/products?q=samsung&category=audio", headers=h)).json() == []

        page = (await c.get("/products?limit=2", headers=h)).json()
        rest = (await c.get("/products?limit=2&offset=2", headers=h)).json()
        assert len(page) == 2 and len(rest) == 1 and not {p["id"] for p in page} & {p["id"] for p in rest}

        cats = (await c.get("/categories", headers=h)).json()
        assert {c_["slug"]: c_["count"] for c_ in cats} == {"audio": 1, "phones": 1, "tv": 1}
        assert (await c.get(f"/products/{everything[0]['id']}", headers=h)).json()["category"] in {"audio", "phones", "tv"}
