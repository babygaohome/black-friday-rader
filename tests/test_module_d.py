import random
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from dealradar.events import EventBus, PriceChanged, StockChanged
from dealradar.models import Offer, PriceHistory, Priority, Retailer, RetailerHealth, ScanJob, StockStatus
from dealradar.retailers.base import RawOffer, RetailerAdapter, ScanError, ScanErrorType
from dealradar.scanning.locks import MemoryLock, scan_lock_key
from dealradar.scanning.retry import retry_delay
from dealradar.scanning.scanner import scan_offer
from dealradar.scanning.schedule import event_factor, health_factor, queue_for, scan_interval, with_jitter


class ScriptedAdapter(RetailerAdapter):
    code, name, domains = "jbhifi", "JB", ("jbhifi.com.au",)

    def __init__(self, *results):
        self.results = list(results)

    async def fetch_product(self, url):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def raw(price="449", avail="In stock", original="549"):
    return RawOffer("jbhifi", "1", "Sony XM6", "https://www.jbhifi.com.au/p", price, original, availability=avail)


async def make_offer(session):
    r = Retailer(code="jbhifi", name="JB", domain="jbhifi.com.au")
    session.add(r)
    await session.flush()
    o = Offer(retailer_id=r.id, retailer_sku="1", url="https://www.jbhifi.com.au/p", title="")
    session.add(o)
    await session.flush()
    return o


class Recorder:
    def __init__(self):
        self.events = []
        self.bus = EventBus()
        self.bus.subscribe(PriceChanged, self.on)
        self.bus.subscribe(StockChanged, self.on)

    async def on(self, e):
        self.events.append(e)


# ---------- scheduling ----------
def test_base_intervals_per_priority():
    s = lambda p, **kw: scan_interval(p, **kw).total_seconds()
    assert s(Priority.LOW) == 1800 and s(Priority.NORMAL) == 600 and s(Priority.HIGH) == 120
    assert 30 <= s(Priority.CRITICAL) <= 60


def test_dynamic_factors():
    base = scan_interval(Priority.NORMAL).total_seconds()
    assert scan_interval(Priority.NORMAL, recent_drop_pct=6).total_seconds() == base * 0.5
    assert scan_interval(Priority.NORMAL, recent_drop_pct=20).total_seconds() == base * 0.2  # 10min -> 2min
    assert scan_interval(Priority.NORMAL, health_status="DEGRADED").total_seconds() > base
    assert scan_interval(Priority.NORMAL, event_mode="BLACK_FRIDAY").total_seconds() == base * 0.5
    assert scan_interval(Priority.CRITICAL, recent_drop_pct=50, event_mode="BLACK_FRIDAY") == timedelta(seconds=30)  # floor
    assert health_factor("ONLINE", 0.72) > 1.8


def test_queues_and_jitter():
    assert queue_for(Priority.CRITICAL) == "scan.high" and queue_for(Priority.LOW) == "scan.low"
    iv = timedelta(seconds=100)
    for seed in range(20):
        assert timedelta(seconds=90) <= with_jitter(iv, random.Random(seed)) <= timedelta(seconds=110)
    assert event_factor("black_friday") == 0.5 and event_factor("x") == 1.0


# ---------- retry ----------
def test_retry_policy():
    rng = random.Random(1)
    delays = [retry_delay(ScanErrorType.NETWORK_ERROR, i, rng) for i in range(4)]
    assert delays[3] is None  # never infinite
    assert 24 <= delays[0].total_seconds() <= 36 and 96 <= delays[1].total_seconds() <= 144
    assert retry_delay(ScanErrorType.PARSE_ERROR, 0) is None
    assert retry_delay(ScanErrorType.PRODUCT_REMOVED, 0) is None
    assert retry_delay(ScanErrorType.RATE_LIMIT, 0).total_seconds() >= 480
    assert retry_delay(ScanErrorType.CAPTCHA, 3) is None


# ---------- lock ----------
async def test_memory_lock_exclusive_and_expires():
    t = [0.0]
    lock = MemoryLock(clock=lambda: t[0])
    assert await lock.acquire("k", 60)
    assert not await lock.acquire("k", 60)
    t[0] = 61
    assert await lock.acquire("k", 60)
    await lock.release("k")
    assert await lock.acquire("k", 60)


# ---------- scanner ----------
async def test_first_scan_records_price_and_emits_event(session):
    offer, rec = await make_offer(session), Recorder()
    res = await scan_offer(session, offer, ScriptedAdapter(raw()), MemoryLock(), rec.bus)
    assert res.status == "OK" and res.price_changed and not res.stock_changed  # unknown -> in stock is not a restock
    assert offer.current_effective_price == Decimal("449.00") and offer.stock_status == StockStatus.IN_STOCK
    assert [type(e) for e in rec.events] == [PriceChanged]
    assert rec.events[0].old_price is None and rec.events[0].new_price == Decimal("449.00")


async def test_unchanged_price_records_history_but_no_event(session):
    offer, rec = await make_offer(session), Recorder()
    adapter = ScriptedAdapter(raw(), raw())
    await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    rec.events.clear()
    res = await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    assert not res.price_changed and rec.events == []
    rows = (await session.execute(select(PriceHistory))).scalars().all()
    assert len(rows) == 2


async def test_price_drop_and_restock_events(session):
    offer, rec = await make_offer(session), Recorder()
    adapter = ScriptedAdapter(raw("449", "Out of stock"), raw("399", "In stock"))
    await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    rec.events.clear()
    res = await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    assert res.price_changed and res.stock_changed
    pc = next(e for e in rec.events if isinstance(e, PriceChanged))
    sc = next(e for e in rec.events if isinstance(e, StockChanged))
    assert (pc.old_price, pc.new_price) == (Decimal("449.00"), Decimal("399.00"))
    assert (sc.from_status, sc.to_status) == (StockStatus.OUT_OF_STOCK, StockStatus.IN_STOCK)


async def test_suspicious_price_is_stored_but_does_not_update_state_or_emit(session):
    offer, rec = await make_offer(session), Recorder()
    adapter = ScriptedAdapter(raw("1999", original="2499"), raw("19.99", original="2499"))
    await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    rec.events.clear()
    res = await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    assert res.status == "FLAGGED" and rec.events == []
    assert offer.current_effective_price == Decimal("1999.00")
    flagged = (await session.execute(select(PriceHistory).where(PriceHistory.flagged.is_(True)))).scalars().all()
    assert len(flagged) == 1


async def test_locked_offer_is_skipped_without_fetching(session):
    offer, rec, lock = await make_offer(session), Recorder(), MemoryLock()
    await lock.acquire(scan_lock_key(offer.id), 60)
    adapter = ScriptedAdapter()  # would IndexError if fetched
    res = await scan_offer(session, offer, adapter, lock, rec.bus)
    assert res.status == "SKIPPED_LOCKED"


async def test_lock_released_after_scan_even_on_failure(session):
    offer, rec, lock = await make_offer(session), Recorder(), MemoryLock()
    await scan_offer(session, offer, ScriptedAdapter(ScanError(ScanErrorType.RATE_LIMIT)), lock, rec.bus)
    assert await lock.acquire(scan_lock_key(offer.id), 60)


async def test_failure_is_recorded_and_degrades_health_without_touching_other_data(session):
    offer, rec = await make_offer(session), Recorder()
    adapter = ScriptedAdapter(raw(), *[ScanError(ScanErrorType.CAPTCHA)] * 8)
    await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    for _ in range(8):
        res = await scan_offer(session, offer, adapter, MemoryLock(), rec.bus)
    assert res.status == "FAILED" and res.error_type == ScanErrorType.CAPTCHA
    assert offer.current_effective_price == Decimal("449.00")
    health = await session.get(RetailerHealth, offer.retailer_id)
    assert health.status in ("DEGRADED", "OFFLINE") and float(health.captcha_rate) > 0
    jobs = (await session.execute(select(ScanJob).where(ScanJob.status == "FAILED"))).scalars().all()
    assert len(jobs) == 8 and jobs[0].error_type == "CAPTCHA"


async def test_invalid_price_is_a_failed_scan(session):
    offer, rec = await make_offer(session), Recorder()
    res = await scan_offer(session, offer, ScriptedAdapter(raw("n/a")), MemoryLock(), rec.bus)
    assert res.status == "FAILED" and res.error_type == ScanErrorType.INVALID_PRICE


# ---------- failure backoff ----------
def _rest_seconds(offer, job_finished):
    return (offer.next_scan_after - job_finished).total_seconds()


async def _fail(session, offer, error):
    res = await scan_offer(session, offer, ScriptedAdapter(ScanError(error)), MemoryLock(), Recorder().bus)
    job = (await session.execute(select(ScanJob).order_by(ScanJob.started_at.desc()).limit(1))).scalars().first()
    return res, job


async def test_repeated_network_failures_back_off_then_slow_down(session):
    offer = await make_offer(session)
    rests = []
    for _ in range(5):
        _, job = await _fail(session, offer, ScanErrorType.NETWORK_ERROR)
        rests.append(_rest_seconds(offer, job.finished_at))
        assert job.next_scan_at == offer.next_scan_after
    for got, base in zip(rests, (30, 120, 600, 3600, 3600)):  # 30s / 2min / 10min, then the hourly cooldown
        assert base * 0.8 - 1 <= got <= base * 1.2 + 1, rests


async def test_blocks_and_dead_pages_rest_longer(session):
    for error, base in ((ScanErrorType.CAPTCHA, 1800), (ScanErrorType.RATE_LIMIT, 600),
                        (ScanErrorType.PARSE_ERROR, 3600), (ScanErrorType.PRODUCT_REMOVED, 3600)):
        offer = await make_offer_for(session, error.value)
        _, job = await _fail(session, offer, error)
        assert base * 0.8 - 1 <= _rest_seconds(offer, job.finished_at) <= base * 1.2 + 1, error


async def make_offer_for(session, sku):
    from dealradar.models import Retailer as R

    retailer = (await session.execute(select(R))).scalars().first() or R(code="jbhifi", name="JB", domain="jbhifi.com.au")
    session.add(retailer)
    await session.flush()
    o = Offer(retailer_id=retailer.id, retailer_sku=sku, url="https://www.jbhifi.com.au/p", title="")
    session.add(o)
    await session.flush()
    return o


async def test_success_clears_the_backoff(session):
    offer = await make_offer(session)
    await _fail(session, offer, ScanErrorType.NETWORK_ERROR)
    assert offer.next_scan_after is not None
    res = await scan_offer(session, offer, ScriptedAdapter(raw()), MemoryLock(), Recorder().bus)
    assert res.status == "OK" and offer.next_scan_after is None


async def test_failure_streak_resets_after_a_success(session):
    offer = await make_offer(session)
    for _ in range(3):
        await _fail(session, offer, ScanErrorType.NETWORK_ERROR)
    await scan_offer(session, offer, ScriptedAdapter(raw()), MemoryLock(), Recorder().bus)
    _, job = await _fail(session, offer, ScanErrorType.NETWORK_ERROR)
    assert 24 - 1 <= _rest_seconds(offer, job.finished_at) <= 36 + 1  # back to the first (30s) step
