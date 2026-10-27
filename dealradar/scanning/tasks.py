"""Celery wiring (M07). Thin: all logic lives in dealradar.runtime / scanner / dispatcher."""
import asyncio
import uuid

from celery import Celery
from kombu import Queue

from dealradar import runtime
from dealradar.core.config import get_settings
from dealradar.scanning.queues import QUEUE_NAMES

settings = get_settings()
celery_app = Celery("dealradar", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_queues = [Queue(name) for name in QUEUE_NAMES]
celery_app.conf.task_default_queue = "scan.normal"
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1  # low-priority backlog must not hold high-priority jobs
celery_app.conf.beat_schedule = {
    "dispatch-due-scans": {"task": "dealradar.dispatch_due_scans", "schedule": 15.0, "options": {"queue": "maintenance"}},
    "retry-notifications": {"task": "dealradar.retry_notifications", "schedule": 60.0, "options": {"queue": "notification"}},
}


def _run(coro):
    return asyncio.run(coro)


@celery_app.task(name="dealradar.scan_offer")
def scan_offer_task(offer_id: str) -> str:
    result = _run(runtime.run_scan(_fresh_runtime(), uuid.UUID(offer_id)))
    return result.status if result else "SKIPPED"


@celery_app.task(name="dealradar.dispatch_due_scans")
def dispatch_due_scans_task() -> int:
    due = _run(runtime.find_due(_fresh_runtime()))
    for d in due:
        scan_offer_task.apply_async(args=[str(d.offer_id)], queue=d.queue)
    return len(due)


@celery_app.task(name="dealradar.retry_notifications")
def retry_notifications_task() -> int:
    return _run(runtime.retry_notifications(_fresh_runtime()))


def _fresh_runtime() -> runtime.Runtime:
    # asyncio.run() creates a new event loop per task, so async engines/clients must not be shared across tasks.
    return runtime.build_runtime(get_settings())
