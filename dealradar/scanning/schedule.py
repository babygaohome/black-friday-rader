"""Dynamic scan scheduling (M06).

scan_interval = base_interval * retailer_health_factor * volatility_factor * event_factor
"""
import random
from datetime import timedelta

from dealradar.models.enums import Priority

BASE_INTERVAL_SECONDS: dict[Priority, int] = {
    Priority.LOW: 30 * 60,
    Priority.NORMAL: 10 * 60,
    Priority.HIGH: 2 * 60,
    Priority.CRITICAL: 45,  # design range 30-60s
}
MIN_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 60 * 60

QUEUE_BY_PRIORITY: dict[Priority, str] = {
    Priority.CRITICAL: "scan.high",
    Priority.HIGH: "scan.high",
    Priority.NORMAL: "scan.normal",
    Priority.LOW: "scan.low",
}

_HEALTH_FACTOR = {"ONLINE": 1.0, "DEGRADED": 2.0, "OFFLINE": 6.0}
_EVENT_FACTOR = {"NORMAL": 1.0, "BLACK_FRIDAY": 0.5}


def health_factor(status: str, success_rate: float = 1.0) -> float:
    """Back off when a retailer is unhealthy: slower scans, never faster."""
    factor = _HEALTH_FACTOR.get(status, 1.0)
    if success_rate < 0.9:
        factor *= 1 + (0.9 - success_rate) * 5  # 72% success -> x1.9
    return factor


def volatility_factor(recent_drop_pct: float = 0.0, volatility: float = 0.0) -> float:
    """Faster scans for items whose price is dropping / moving."""
    if recent_drop_pct >= 15:
        return 0.2
    if recent_drop_pct >= 5:
        return 0.5
    if volatility >= 0.1:
        return 0.7
    return 1.0


def event_factor(event_mode: str) -> float:
    return _EVENT_FACTOR.get(event_mode.upper(), 1.0)


def scan_interval(
    priority: Priority,
    health_status: str = "ONLINE",
    success_rate: float = 1.0,
    recent_drop_pct: float = 0.0,
    volatility: float = 0.0,
    event_mode: str = "NORMAL",
) -> timedelta:
    seconds = (
        BASE_INTERVAL_SECONDS[priority]
        * health_factor(health_status, success_rate)
        * volatility_factor(recent_drop_pct, volatility)
        * event_factor(event_mode)
    )
    return timedelta(seconds=max(MIN_INTERVAL_SECONDS, min(MAX_INTERVAL_SECONDS, seconds)))


def queue_for(priority: Priority) -> str:
    return QUEUE_BY_PRIORITY[priority]


def with_jitter(interval: timedelta, rng: random.Random | None = None, spread: float = 0.1) -> timedelta:
    """+/- spread so offers don't all fire on the same tick."""
    r = (rng or random).uniform(-spread, spread)
    return interval * (1 + r)
