import time
from typing import Protocol

LOCK_TTL_SECONDS = 90  # design doc: 60-120s


def scan_lock_key(offer_id) -> str:
    return f"scan_lock:{offer_id}"


class LockBackend(Protocol):
    async def acquire(self, key: str, ttl: int) -> bool: ...
    async def release(self, key: str) -> None: ...


class MemoryLock:
    """In-process lock for tests / single-process dev. Honors TTL like Redis would."""

    def __init__(self, clock=time.monotonic) -> None:
        self._held: dict[str, float] = {}
        self._clock = clock

    async def acquire(self, key: str, ttl: int) -> bool:
        now = self._clock()
        if self._held.get(key, 0) > now:
            return False
        self._held[key] = now + ttl
        return True

    async def release(self, key: str) -> None:
        self._held.pop(key, None)


class RedisLock:
    """SET key NX EX ttl on a redis.asyncio client."""

    def __init__(self, client) -> None:
        self._r = client

    async def acquire(self, key: str, ttl: int) -> bool:
        return bool(await self._r.set(key, "1", nx=True, ex=ttl))

    async def release(self, key: str) -> None:
        await self._r.delete(key)
