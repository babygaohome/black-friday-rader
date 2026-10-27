"""Celery wiring (M07). Thin: all logic lives in scanner/schedule so it is testable without a broker."""
from celery import Celery
from kombu import Queue

from dealradar.core.config import get_settings

settings = get_settings()
celery_app = Celery("dealradar", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_queues = [
    Queue(name)
    for name in ("scan.high", "scan.normal", "scan.low", "alert.high", "alert.normal", "notification", "maintenance")
]
celery_app.conf.task_default_queue = "scan.normal"
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1  # low-priority backlog must not hold high-priority jobs


@celery_app.task(name="dealradar.scan_offer")
def scan_offer_task(offer_id: str) -> str:
    """Entry point; enqueue with queue=queue_for(priority). Wiring to DB/adapters lands with the API service."""
    raise NotImplementedError("scan_offer_task is wired in the service layer")
