"""Infrastructure probes for the admin panel: Redis queue lengths and Celery worker liveness."""
import asyncio
from typing import Awaitable, Callable

from dealradar.scanning.queues import QUEUE_NAMES

QueueStats = Callable[[], Awaitable[dict[str, int]]]
WorkerStats = Callable[[], Awaitable[list[dict]]]


def redis_queue_stats(client, names=QUEUE_NAMES) -> QueueStats:
    """Celery's Redis broker keeps each queue as a list named after the queue."""

    async def stats() -> dict[str, int]:
        return {name: int(await client.llen(name)) for name in names}

    return stats


def celery_worker_stats(celery_app, timeout: float = 1.0) -> WorkerStats:
    """inspect() is a blocking broadcast-and-wait call, so it runs in a thread with a short timeout."""

    def probe() -> list[dict]:
        inspector = celery_app.control.inspect(timeout=timeout)
        pong = inspector.ping() or {}
        active = inspector.active() or {}
        return [{"name": name, "online": True, "active_tasks": len(active.get(name, []))} for name in sorted(pong)]

    async def stats() -> list[dict]:
        return await asyncio.to_thread(probe)

    return stats
