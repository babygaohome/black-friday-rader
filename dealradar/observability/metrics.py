"""Prometheus text exposition (M19). API metrics are per process; scraper and business metrics are read from
the database at scrape time, so they are correct no matter which process (API or Celery worker) produced the data."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import Alert, Offer, PriceHistory, Retailer, RetailerHealth, ScanJob

LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
Sample = tuple[dict[str, str], float]


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(name: str, kind: str, help_: str, samples: list[Sample]) -> list[str]:
    lines = [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
    for labels, value in samples:
        label_text = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_text}}} {value}" if label_text else f"{name} {value}")
    return lines


class AppMetrics:
    """API latency and errors, keyed by route template (never the raw path, which would explode label cardinality)."""

    def __init__(self) -> None:
        self._requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._buckets: dict[str, list[int]] = defaultdict(lambda: [0] * len(LATENCY_BUCKETS))
        self._sum: dict[str, float] = defaultdict(float)
        self._count: dict[str, int] = defaultdict(int)

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self._requests[(method, route, str(status))] += 1
        self._sum[route] += seconds
        self._count[route] += 1
        for i, upper in enumerate(LATENCY_BUCKETS):
            if seconds <= upper:
                self._buckets[route][i] += 1

    def render(self, ws_clients: int) -> list[str]:
        out = render("dealradar_http_requests_total", "counter", "HTTP requests by route and status", [
            ({"method": m, "route": r, "status": s}, n) for (m, r, s), n in sorted(self._requests.items())])
        name = "dealradar_http_request_duration_seconds"
        out += [f"# HELP {name} Request latency", f"# TYPE {name} histogram"]
        for route in sorted(self._count):
            for upper, n in zip(LATENCY_BUCKETS, self._buckets[route]):
                out.append(f'{name}_bucket{{route="{_escape(route)}",le="{upper}"}} {n}')
            out.append(f'{name}_bucket{{route="{_escape(route)}",le="+Inf"}} {self._count[route]}')
            out.append(f'{name}_sum{{route="{_escape(route)}"}} {round(self._sum[route], 6)}')
            out.append(f'{name}_count{{route="{_escape(route)}"}} {self._count[route]}')
        out += render("dealradar_websocket_clients", "gauge", "Connected WebSocket clients", [({}, ws_clients)])
        return out


async def db_metrics(session: AsyncSession, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    hour, day = now - timedelta(hours=1), now - timedelta(hours=24)

    scans = (await session.execute(
        select(Retailer.code, ScanJob.status, func.count())
        .join(Offer, Offer.id == ScanJob.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(ScanJob.finished_at >= hour).group_by(Retailer.code, ScanJob.status)
    )).all()
    errors = (await session.execute(
        select(Retailer.code, ScanJob.error_type, func.count())
        .join(Offer, Offer.id == ScanJob.offer_id).join(Retailer, Retailer.id == Offer.retailer_id)
        .where(ScanJob.status == "FAILED", ScanJob.finished_at >= hour).group_by(Retailer.code, ScanJob.error_type)
    )).all()
    health = (await session.execute(
        select(Retailer.code, RetailerHealth.success_rate, RetailerHealth.captcha_rate, RetailerHealth.status)
        .join(RetailerHealth, RetailerHealth.retailer_id == Retailer.id)
    )).all()
    alerts = (await session.execute(
        select(Alert.type, func.count()).where(Alert.created_at >= day).group_by(Alert.type))).all()

    lag = func.lag(PriceHistory.effective_price).over(
        partition_by=PriceHistory.offer_id, order_by=PriceHistory.timestamp)
    inner = (
        select(PriceHistory.effective_price.label("price"), lag.label("prev"), PriceHistory.timestamp.label("ts"))
        .where(PriceHistory.flagged.is_(False), PriceHistory.timestamp >= now - timedelta(hours=48))
        .subquery()
    )
    changes = (await session.execute(
        select(func.count()).select_from(inner).where(inner.c.ts >= day, inner.c.prev.is_not(None), inner.c.price != inner.c.prev)
    )).scalar_one()
    flagged = (await session.execute(
        select(func.count()).select_from(PriceHistory).where(PriceHistory.flagged.is_(True), PriceHistory.timestamp >= day)
    )).scalar_one()

    out = render("dealradar_scans_1h", "gauge", "Finished scans in the last hour", [
        ({"retailer": c, "status": s}, n) for c, s, n in scans])
    out += render("dealradar_scan_failures_1h", "gauge",
                  "Failed scans in the last hour by error type (PARSE_ERROR = parse failures, NETWORK_ERROR = HTTP errors, CAPTCHA/RATE_LIMIT = blocks)",
                  [({"retailer": c, "error_type": e or "UNKNOWN"}, n) for c, e, n in errors])
    out += render("dealradar_retailer_success_rate", "gauge", "Smoothed scan success rate", [
        ({"retailer": c}, float(sr)) for c, sr, _, _ in health])
    out += render("dealradar_retailer_captcha_rate", "gauge", "Smoothed captcha/rate-limit rate", [
        ({"retailer": c}, float(cr)) for c, _, cr, _ in health])
    out += render("dealradar_retailer_status", "gauge", "1 for the retailer's current health status", [
        ({"retailer": c, "status": st}, 1) for c, _, _, st in health])
    out += render("dealradar_price_changes_24h", "gauge", "Price changes (flagged observations excluded) in the last 24h", [({}, changes)])
    out += render("dealradar_suspicious_prices_24h", "gauge", "Flagged suspicious price observations in the last 24h", [({}, flagged)])
    out += render("dealradar_alerts_24h", "gauge",
                  "Alerts created in the last 24h by type (TARGET_PRICE_HIT = target hits, RESTOCK = restocks)",
                  [({"type": t.value}, n) for t, n in alerts])
    return out
