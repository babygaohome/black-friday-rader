"""WebSocket fan-out (M17). One Hub per API process; every connected client owns a bounded queue."""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Protocol

log = logging.getLogger(__name__)

PRICE_UPDATED = "price.updated"
STOCK_UPDATED = "stock.updated"
DEAL_CREATED = "deal.created"
ALERT_TRIGGERED = "alert.triggered"
SCANNER_STATUS = "scanner.status"
TOPICS = frozenset({PRICE_UPDATED, STOCK_UPDATED, DEAL_CREATED, ALERT_TRIGGERED, SCANNER_STATUS})

QUEUE_SIZE = 100


def make_message(event: str, data: dict, user_id: str | None = None) -> dict:
    """user_id marks a private message: only that user's sockets receive it."""
    return {"event": event, "data": data, "user_id": user_id, "ts": datetime.now(timezone.utc).isoformat()}


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def dumps(message: dict) -> str:
    return json.dumps(message, default=_default)


@dataclass(eq=False)
class Client:
    user_id: str
    topics: set[str]
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    dropped: int = 0


class Hub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()

    def connect(self, user_id: str, topics: set[str] | None = None) -> Client:
        client = Client(user_id, set(topics) if topics else set(TOPICS))
        self._clients.add(client)
        return client

    def disconnect(self, client: Client) -> None:
        self._clients.discard(client)

    @property
    def size(self) -> int:
        return len(self._clients)

    def broadcast(self, message: dict) -> int:
        """Deliver to every matching client; a slow client loses its oldest messages instead of blocking others."""
        sent = 0
        private_to = message.get("user_id")
        public = {k: v for k, v in message.items() if k != "user_id"}
        for c in list(self._clients):
            if message["event"] not in c.topics or (private_to is not None and private_to != c.user_id):
                continue
            if c.queue.full():
                c.queue.get_nowait()
                c.dropped += 1
            c.queue.put_nowait(public)
            sent += 1
        return sent


class Broadcaster(Protocol):
    async def publish(self, message: dict) -> None: ...


class LocalBroadcaster:
    """Same-process delivery (API process, tests)."""

    def __init__(self, hub: Hub) -> None:
        self._hub = hub

    async def publish(self, message: dict) -> None:
        self._hub.broadcast(message)


class NullBroadcaster:
    async def publish(self, message: dict) -> None:
        return None


REDIS_CHANNEL = "dealradar:realtime"


class RedisBroadcaster:
    """Used by Celery workers: publishes to Redis; each API process relays into its own Hub."""

    def __init__(self, client, channel: str = REDIS_CHANNEL) -> None:
        self._client = client
        self._channel = channel

    async def publish(self, message: dict) -> None:
        await self._client.publish(self._channel, dumps(message))


async def run_redis_relay(client, hub: Hub, channel: str = REDIS_CHANNEL) -> None:
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for item in pubsub.listen():
            if item.get("type") != "message":
                continue
            try:
                message = json.loads(item["data"])
                if message.get("event") in TOPICS:
                    hub.broadcast(message)
            except Exception:  # a malformed message must not kill the relay
                log.exception("bad realtime message")
    finally:
        await pubsub.unsubscribe(channel)


Relay = Callable[[Hub], Awaitable[None]]
