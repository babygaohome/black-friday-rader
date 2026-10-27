"""Wires settings -> engine, adapters, locks, alert engine. Used by the Celery workers and the API entry point."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from dealradar.alerts.cooldown import CooldownStore, RedisCooldown
from dealradar.alerts.engine import AlertEngine
from dealradar.core.config import Settings
from dealradar.core.db import make_engine, make_session_factory
from dealradar.events import EventBus
from dealradar.models import Notification, NotificationStatus, Offer, Retailer
from dealradar.notifications.telegram import TelegramNotifier
from dealradar.retailers.builtin import build_default_registry
from dealradar.retailers.registry import RetailerRegistry
from dealradar.scanning.dispatcher import DueScan, due_scans
from dealradar.scanning.locks import LockBackend, RedisLock
from dealradar.scanning.scanner import ScanResult, scan_offer


@dataclass
class Runtime:
    session_factory: object
    registry: RetailerRegistry
    lock: LockBackend
    bus: EventBus
    notifier: TelegramNotifier | None
    event_mode: str = "NORMAL"


def build_runtime(settings: Settings, lock: LockBackend | None = None, cooldown: CooldownStore | None = None,
                  registry: RetailerRegistry | None = None, notifier_transport=None, session_factory=None) -> Runtime:
    if lock is None or cooldown is None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        lock = lock or RedisLock(client)
        cooldown = cooldown or RedisCooldown(client)
    sf = session_factory or make_session_factory(make_engine(settings.database_url))
    notifier = TelegramNotifier(settings.telegram_bot_token, notifier_transport) if (
        settings.telegram_bot_token or notifier_transport) else None
    bus = EventBus()
    AlertEngine(sf, cooldown, notifier).register(bus)
    return Runtime(sf, registry or build_default_registry(), lock, bus, notifier, settings.event_mode)


async def run_scan(rt: Runtime, offer_id: uuid.UUID) -> ScanResult | None:
    async with rt.session_factory() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None or not offer.active:
            return None
        retailer = await session.get(Retailer, offer.retailer_id)
        if retailer is None or retailer.code not in rt.registry.codes():
            return None
        return await scan_offer(session, offer, rt.registry.get(retailer.code), rt.lock, rt.bus)


async def find_due(rt: Runtime) -> list[DueScan]:
    async with rt.session_factory() as session:
        return await due_scans(session, event_mode=rt.event_mode)


async def retry_notifications(rt: Runtime) -> int:
    """Re-attempt notifications left in RETRY (each delivery attempt is capped by the notifier)."""
    if rt.notifier is None:
        return 0
    async with rt.session_factory() as session:
        ids = (await session.execute(select(Notification.id).where(Notification.status == NotificationStatus.RETRY))).scalars().all()
        for nid in ids:
            await rt.notifier.deliver(session, nid)
        return len(ids)
