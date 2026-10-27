import time
from typing import Protocol


def cooldown_key(user_id, watch_id, alert_type) -> str:
    return f"alert:{user_id}:{watch_id}:{getattr(alert_type, 'value', alert_type)}"


class CooldownStore(Protocol):
    async def try_acquire(self, key: str, ttl_seconds: int) -> bool:
        """True if no alert was sent within the TTL (and records this one)."""


class MemoryCooldown:
    def __init__(self, clock=time.monotonic) -> None:
        self._until: dict[str, float] = {}
        self._clock = clock

    async def try_acquire(self, key: str, ttl_seconds: int) -> bool:
        now = self._clock()
        if self._until.get(key, 0) > now:
            return False
        self._until[key] = now + ttl_seconds
        return True


class RedisCooldown:
    def __init__(self, client) -> None:
        self._r = client

    async def try_acquire(self, key: str, ttl_seconds: int) -> bool:
        return bool(await self._r.set(key, "1", nx=True, ex=ttl_seconds))
