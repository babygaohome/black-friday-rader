import asyncio
import json
import uuid
from decimal import Decimal

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.api.app import create_app
from dealradar.core.config import Settings
from dealradar.core.db import create_all, make_engine, make_session_factory
from dealradar.events import PriceChanged
from dealradar.models import StockStatus
from dealradar.realtime.hub import (
    ALERT_TRIGGERED, DEAL_CREATED, PRICE_UPDATED, SCANNER_STATUS, STOCK_UPDATED, TOPICS,
    Hub, LocalBroadcaster, RedisBroadcaster, dumps, make_message, run_redis_relay,
)
from dealradar.realtime.publisher import RealtimePublisher
from dealradar.retailers.registry import RetailerRegistry
from dealradar.runtime import build_runtime, find_due, run_scan
from dealradar.scanning.locks import MemoryLock
from tests.test_module_f import URL, Site, signup  # noqa: F401  (reuse the fake jbhifi site + signup helper)
from retailers.jbhifi.adapter import JBHiFiAdapter


def drain(client) -> list[dict]:
    out = []
    while not client.queue.empty():
        out.append(client.queue.get_nowait())
    return out


# ---------- hub ----------
def test_hub_filters_by_topic_and_privacy():
    hub = Hub()
    everyone = hub.connect("u1")
    prices_only = hub.connect("u2", {PRICE_UPDATED})
    hub.broadcast(make_message(PRICE_UPDATED, {"x": 1}))
    hub.broadcast(make_message(STOCK_UPDATED, {"x": 2}))
    hub.broadcast(make_message(ALERT_TRIGGERED, {"x": 3}, user_id="u1"))
    assert [m["event"] for m in drain(everyone)] == [PRICE_UPDATED, STOCK_UPDATED, ALERT_TRIGGERED]
    assert [m["event"] for m in drain(prices_only)] == [PRICE_UPDATED]


def test_private_message_never_reaches_other_users_and_hides_user_id():
    hub = Hub()
    mine, theirs = hub.connect("u1"), hub.connect("u2")
    assert hub.broadcast(make_message(ALERT_TRIGGERED, {"a": 1}, user_id="u1")) == 1
    [msg] = drain(mine)
    assert "user_id" not in msg and drain(theirs) == []


def test_slow_client_drops_oldest_without_blocking_others():
    hub = Hub()
    slow, fast = hub.connect("u1"), hub.connect("u2")
    for i in range(slow.queue.maxsize + 5):
        hub.broadcast(make_message(PRICE_UPDATED, {"i": i}))
        if i % 2 == 0:
            drain(fast)
    assert slow.dropped == 5 and slow.queue.qsize() == slow.queue.maxsize
    assert drain(slow)[0]["data"]["i"] == 5  # the five oldest were discarded
    assert fast.dropped == 0


def test_disconnect_stops_delivery():
    hub = Hub()
    c = hub.connect("u1")
    hub.disconnect(c)
    assert hub.size == 0 and hub.broadcast(make_message(PRICE_UPDATED, {})) == 0


def test_dumps_handles_decimal_and_datetime():
    out = json.loads(dumps(make_message(PRICE_UPDATED, {"price": Decimal("399.50")})))
    assert out["data"]["price"] == 399.5 and out["ts"]


# ---------- redis relay ----------
class FakePubSub:
    def __init__(self, items):
        self.items, self.subscribed = items, []

    async def subscribe(self, ch):
        self.subscribed.append(ch)

    async def unsubscribe(self, ch):
        self.subscribed.remove(ch)

    async def listen(self):
        for i in self.items:
            yield i


class FakeRedis:
    def __init__(self, items=()):
        self.published, self._ps = [], FakePubSub(list(items))

    async def publish(self, ch, payload):
        self.published.append((ch, payload))

    def pubsub(self):
        return self._ps


async def test_redis_broadcaster_and_relay_roundtrip():
    r = FakeRedis()
    await RedisBroadcaster(r).publish(make_message(PRICE_UPDATED, {"price": Decimal("10")}, user_id="u1"))
    [(channel, payload)] = r.published

    hub = Hub()
    c = hub.connect("u1")
    relay = FakeRedis([
        {"type": "subscribe", "data": 1},                                   # control frame, ignored
        {"type": "message", "data": b"not json"},                           # malformed, must not kill the relay
        {"type": "message", "data": json.dumps({"event": "evil.topic", "data": {}})},
        {"type": "message", "data": payload},
    ])
    await run_redis_relay(relay, hub, channel)
    [msg] = drain(c)
    assert msg["event"] == PRICE_UPDATED and msg["data"]["price"] == 10 and relay.pubsub().subscribed == []


# ---------- publisher wired through the real scan loop ----------
@pytest.fixture
def site():
    return Site()


@pytest.fixture
def registry(site):
    r = RetailerRegistry()
    r.register(JBHiFiAdapter(fetcher=site))
    return r


@pytest.fixture
async def api(factory, registry):
    hub = Hub()
    app = create_app(factory, registry, secret_key="test-secret", hub=hub)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, hub


def runtime(factory, registry, hub):
    return build_runtime(
        Settings(database_url="sqlite+aiosqlite:///:memory:"), lock=MemoryLock(), cooldown=MemoryCooldown(),
        registry=registry, session_factory=factory, broadcaster=LocalBroadcaster(hub),
    )


async def watch(client, headers) -> None:
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=headers)).json()["product_id"]
    await client.post("/watchlist", json={"product_id": pid, "target_price": "400"}, headers=headers)


async def user_id_of(client, headers) -> str:
    return (await client.get("/users/me", headers=headers)).json()["id"]


async def test_scan_pushes_price_alert_and_scanner_status(factory, registry, site, api):
    client, hub = api
    owner_h = await signup(client, "owner@example.com")
    other_h = await signup(client, "other@example.com")
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=owner_h)).json()["product_id"]
    await client.post("/watchlist", json={"product_id": pid, "target_price": "400"}, headers=owner_h)

    owner = hub.connect(await user_id_of(client, owner_h))
    other = hub.connect(await user_id_of(client, other_h))
    rt = runtime(factory, registry, hub)
    [due] = await find_due(rt)
    site.page = "jbhifi_sale.html"
    await run_scan(rt, due.offer_id)

    owner_events = {m["event"]: m for m in drain(owner)}
    assert set(owner_events) == {PRICE_UPDATED, ALERT_TRIGGERED, SCANNER_STATUS}  # 2 history points: not "verified", so no deal.created
    price = owner_events[PRICE_UPDATED]["data"]
    assert price["retailer"] == "jbhifi" and price["price"] == 399 and price["old_price"] == 549 and price["product"]
    alert = owner_events[ALERT_TRIGGERED]["data"]
    assert alert["type"] == "TARGET_PRICE_HIT" and alert["price"] == 399
    assert owner_events[SCANNER_STATUS]["data"] == {
        "retailer": "jbhifi", "offer_id": str(due.offer_id), "status": "OK", "error_type": None}
    # someone else sees the market data but never another user's alert
    assert {m["event"] for m in drain(other)} == {PRICE_UPDATED, SCANNER_STATUS}


async def test_failed_scan_reports_error_type(factory, registry, site, api):
    client, hub = api
    h = await signup(client)
    await watch(client, h)
    watcher = hub.connect(await user_id_of(client, h), {SCANNER_STATUS})
    rt = runtime(factory, registry, hub)
    [due] = await find_due(rt)

    async def blocked(url):
        return httpx.Response(403, text="denied", request=httpx.Request("GET", url))

    registry.get("jbhifi")._fetcher = blocked  # adapter fetcher swapped to simulate a block
    await run_scan(rt, due.offer_id)
    [msg] = drain(watcher)
    assert msg["data"]["status"] == "FAILED" and msg["data"]["error_type"]


async def test_deal_created_for_high_scoring_drop(factory, registry, site, api):
    client, hub = api
    h = await signup(client)
    await watch(client, h)
    watcher = hub.connect(await user_id_of(client, h), {DEAL_CREATED})
    pub = RealtimePublisher(factory, LocalBroadcaster(hub), deal_min_score=0)
    rt = runtime(factory, registry, hub)
    [due] = await find_due(rt)
    site.page = "jbhifi_sale.html"
    await run_scan(rt, due.offer_id)
    assert drain(watcher) == []  # default threshold (85) not reached

    await pub.on_price_changed(PriceChanged(due.offer_id, Decimal("549"), Decimal("399"), Decimal("699"), StockStatus.IN_STOCK))
    [deal] = drain(watcher)
    assert deal["event"] == DEAL_CREATED and deal["data"]["deal_score"] >= 0 and deal["data"]["grade"]

    # price increases are never announced as deals
    await pub.on_price_changed(PriceChanged(due.offer_id, Decimal("399"), Decimal("549")))
    assert drain(watcher) == []


async def test_publisher_survives_broadcast_failure(factory, registry, site, api):
    client, hub = api
    await watch(client, await signup(client))

    class Broken:
        async def publish(self, message):
            raise ConnectionError("redis down")

    rt = runtime(factory, registry, hub)
    rt.realtime._out = Broken()
    [due] = await find_due(rt)
    site.page = "jbhifi_sale.html"
    result = await run_scan(rt, due.offer_id)  # scanning and alerting carry on
    assert result.status == "OK" and result.price_changed


# ---------- websocket endpoint ----------
@pytest.fixture
def ws_app(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'ws.db'}")
    factory = make_session_factory(engine)
    hub = Hub()
    app = create_app(factory, RetailerRegistry(), secret_key="test-secret", hub=hub)
    with TestClient(app) as tc:
        tc.portal.call(create_all, engine)
        yield tc, hub


def register(tc, email="ws@example.com"):
    r = tc.post("/auth/register", json={"email": email, "password": "password123"})
    return r.json()["token"], r.json()["id"]


def test_ws_rejects_missing_bad_token_and_unknown_topic(ws_app):
    tc, _ = ws_app
    token, _ = register(tc)
    for url in ["/ws", "/ws?token=garbage", f"/ws?token={token}x"]:
        with pytest.raises(WebSocketDisconnect) as e:
            with tc.websocket_connect(url):
                pass
        assert e.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as e:
        with tc.websocket_connect(f"/ws?token={token}&topics=price.updated,nope"):
            pass
    assert e.value.code == 4400


def test_ws_unknown_user_with_valid_signature_is_rejected(ws_app):
    from dealradar.core.security import issue_token

    tc, _ = ws_app
    ghost = issue_token("test-secret", str(uuid.uuid4()), 60)
    with pytest.raises(WebSocketDisconnect) as e:
        with tc.websocket_connect(f"/ws?token={ghost}"):
            pass
    assert e.value.code == 4401


def test_ws_receives_filtered_messages_ping_and_resubscribe(ws_app):
    tc, hub = ws_app
    token, uid = register(tc)
    with tc.websocket_connect(f"/ws?token={token}&topics=price.updated") as ws:
        assert ws.receive_json() == {"event": "connected", "data": {"topics": ["price.updated"]}}
        assert hub.size == 1

        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"event": "pong"}

        tc.portal.call(hub.broadcast, make_message(STOCK_UPDATED, {"n": 1}))   # filtered out
        tc.portal.call(hub.broadcast, make_message(PRICE_UPDATED, {"n": 2}))
        msg = ws.receive_json()
        assert msg["event"] == PRICE_UPDATED and msg["data"] == {"n": 2} and "user_id" not in msg

        ws.send_json({"action": "subscribe", "topics": ["stock.updated", "bogus"]})
        assert ws.receive_json()["data"]["topics"] == ["stock.updated"]
        tc.portal.call(hub.broadcast, make_message(STOCK_UPDATED, {"n": 3}))
        assert ws.receive_json()["data"] == {"n": 3}

        tc.portal.call(hub.broadcast, make_message(ALERT_TRIGGERED, {"n": 4}, user_id=str(uuid.uuid4())))  # someone else's
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"event": "pong"}  # nothing leaked ahead of the pong
    assert hub.size == 0  # disconnect cleans up


def test_ws_delivers_decimal_payloads_and_stays_open(ws_app):
    """Real events carry Decimal prices; a serialisation failure used to drop the socket."""
    tc, hub = ws_app
    token, _ = register(tc)
    with tc.websocket_connect(f"/ws?token={token}") as ws:
        ws.receive_json()
        tc.portal.call(hub.broadcast, make_message(PRICE_UPDATED, {"price": Decimal("399.50"), "old_price": Decimal("549")}))
        msg = ws.receive_json()
        assert msg["data"] == {"price": 399.5, "old_price": 549}
        tc.portal.call(hub.broadcast, make_message(STOCK_UPDATED, {"n": 1}))
        assert ws.receive_json()["data"] == {"n": 1}  # connection survived


def test_topics_constant_matches_design_doc():
    assert TOPICS == {"price.updated", "stock.updated", "deal.created", "alert.triggered", "scanner.status"}


def test_deal_threshold_depends_on_event_mode():
    from dealradar.realtime.publisher import deal_min_score

    assert deal_min_score("NORMAL") == 85
    assert deal_min_score("black_friday") == 90
    assert deal_min_score("BLACK_FRIDAY", 80, 95) == 95
