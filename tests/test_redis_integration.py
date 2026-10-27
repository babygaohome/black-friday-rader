"""Against a real Redis. Skipped unless DEALRADAR_TEST_REDIS_URL is set, e.g. redis://localhost:6379/15
(the database is flushed, so point it at a scratch one)."""
import asyncio
import json
import os
import uuid

import pytest

from dealradar.alerts.cooldown import RedisCooldown, cooldown_key
from dealradar.models import AlertType
from dealradar.realtime.hub import PRICE_UPDATED, Hub, RedisBroadcaster, make_message, run_redis_relay
from dealradar.scanning.locks import RedisLock, scan_lock_key

URL = os.environ.get("DEALRADAR_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DEALRADAR_TEST_REDIS_URL not set")


@pytest.fixture
async def redis():
    import redis.asyncio as aioredis

    client = aioredis.from_url(URL)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


async def test_lock_is_exclusive_expires_and_releases(redis):
    lock, key = RedisLock(redis), scan_lock_key(uuid.uuid4())
    assert await lock.acquire(key, 90) is True
    assert await lock.acquire(key, 90) is False  # second worker backs off
    assert 0 < await redis.ttl(key) <= 90
    await lock.release(key)
    assert await lock.acquire(key, 1) is True
    await asyncio.sleep(1.2)
    assert await lock.acquire(key, 90) is True  # expired on its own (crashed worker)


async def test_cooldown_blocks_repeat_alerts_until_ttl(redis):
    store = RedisCooldown(redis)
    key = cooldown_key(uuid.uuid4(), uuid.uuid4(), AlertType.TARGET_PRICE_HIT)
    assert await store.try_acquire(key, 1) is True
    assert await store.try_acquire(key, 1) is False
    await asyncio.sleep(1.2)
    assert await store.try_acquire(key, 1) is True


async def test_worker_to_api_realtime_relay(redis):
    """What a Celery worker publishes reaches a client connected to an API process's hub."""
    hub = Hub()
    client = hub.connect("u1")
    relay = asyncio.create_task(run_redis_relay(redis, hub))
    await asyncio.sleep(0.3)  # let it subscribe

    from decimal import Decimal

    await RedisBroadcaster(redis).publish(make_message(PRICE_UPDATED, {"price": Decimal("399.5")}))
    msg = await asyncio.wait_for(client.queue.get(), 3)
    assert msg["event"] == PRICE_UPDATED and msg["data"]["price"] == 399.5

    await redis.publish("dealradar:realtime", "garbage")
    await redis.publish("dealradar:realtime", json.dumps({"event": "evil", "data": {}}))
    await RedisBroadcaster(redis).publish(make_message(PRICE_UPDATED, {"price": 1}))
    assert (await asyncio.wait_for(client.queue.get(), 3))["data"]["price"] == 1  # junk skipped, relay alive
    relay.cancel()
    with pytest.raises(asyncio.CancelledError):
        await relay
