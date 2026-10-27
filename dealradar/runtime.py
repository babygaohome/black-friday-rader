"""Wires settings -> engine, adapters, locks, alert engine. Used by the Celery workers and the API entry point."""
import logging
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
from dealradar.observability.logs import log_event
from dealradar.realtime.hub import Broadcaster, NullBroadcaster, RedisBroadcaster
from dealradar.realtime.publisher import RealtimePublisher, deal_min_score
from dealradar.retailers.builtin import build_default_registry
from dealradar.retailers.registry import RetailerRegistry
from dealradar.scanning.dispatcher import DueScan, claim, due_scans
from dealradar.scanning.locks import LockBackend, RedisLock
from dealradar.scanning.scanner import ScanResult, scan_offer


log = logging.getLogger(__name__)


@dataclass
class Runtime:
    session_factory: object
    registry: RetailerRegistry
    lock: LockBackend
    bus: EventBus
    notifier: TelegramNotifier | None
    event_mode: str = "NORMAL"
    realtime: RealtimePublisher | None = None


def build_runtime(settings: Settings, lock: LockBackend | None = None, cooldown: CooldownStore | None = None,
                  registry: RetailerRegistry | None = None, notifier_transport=None, session_factory=None,
                  broadcaster: Broadcaster | None = None) -> Runtime:
    if lock is None or cooldown is None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        lock = lock or RedisLock(client)
        cooldown = cooldown or RedisCooldown(client)
        broadcaster = broadcaster or RedisBroadcaster(client)
    broadcaster = broadcaster or NullBroadcaster()
    sf = session_factory or make_session_factory(make_engine(settings.database_url))
    notifier = TelegramNotifier(settings.telegram_bot_token, notifier_transport) if (
        settings.telegram_bot_token or notifier_transport) else None
    bus = EventBus()
    realtime = RealtimePublisher(
        sf, broadcaster,
        deal_min_score=deal_min_score(settings.event_mode, settings.deal_min_score, settings.black_friday_deal_min_score),
    )
    AlertEngine(sf, cooldown, notifier, on_alert=realtime.on_alert).register(bus)
    realtime.register(bus)
    return Runtime(sf, registry or build_default_registry(), lock, bus, notifier, settings.event_mode, realtime)


async def run_scan(rt: Runtime, offer_id: uuid.UUID) -> ScanResult | None:
    async with rt.session_factory() as session:
        offer = await session.get(Offer, offer_id)
        if offer is None or not offer.active:
            return None
        retailer = await session.get(Retailer, offer.retailer_id)
        if retailer is None or retailer.code not in rt.registry.codes():
            return None
        result = await scan_offer(session, offer, rt.registry.get(retailer.code), rt.lock, rt.bus)
        log_event(
            log, f"scan_{result.status.lower()}", logging.WARNING if result.status == "FAILED" else logging.INFO,
            retailer=retailer.code, offer_id=str(offer_id),
            error=result.error_type.value.lower() if result.error_type else None,
            price_changed=result.price_changed or None, stock_changed=result.stock_changed or None,
        )
        if rt.realtime and result.status != "SKIPPED_LOCKED":
            await rt.realtime.on_scan(
                retailer.code, offer_id, result.status, result.error_type.value if result.error_type else None)
        return result


async def find_due(rt: Runtime) -> list[DueScan]:
    async with rt.session_factory() as session:
        return await due_scans(session, event_mode=rt.event_mode)


async def claim_due(rt: Runtime) -> list[DueScan]:
    """What the scheduler tick enqueues: the due offers, marked so the next tick skips them."""
    async with rt.session_factory() as session:
        due = await due_scans(session, event_mode=rt.event_mode)
        await claim(session, due)
        return due


async def retry_notifications(rt: Runtime) -> int:
    """Re-attempt notifications left in RETRY (each delivery attempt is capped by the notifier)."""
    if rt.notifier is None:
        return 0
    async with rt.session_factory() as session:
        ids = (await session.execute(select(Notification.id).where(Notification.status == NotificationStatus.RETRY))).scalars().all()
        for nid in ids:
            await rt.notifier.deliver(session, nid)
        return len(ids)
