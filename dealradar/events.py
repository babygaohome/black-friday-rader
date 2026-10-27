"""Domain events (design doc section 55). Scanning, deal and alert logic only talk through these."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable

from dealradar.models.enums import StockStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PriceChanged:
    offer_id: uuid.UUID
    old_price: Decimal | None
    new_price: Decimal
    original_price: Decimal | None = None
    stock: StockStatus = StockStatus.UNKNOWN
    timestamp: datetime = field(default_factory=_now)
    event: str = "price.changed"


@dataclass(frozen=True)
class StockChanged:
    offer_id: uuid.UUID
    from_status: StockStatus
    to_status: StockStatus
    price: Decimal | None = None
    timestamp: datetime = field(default_factory=_now)
    event: str = "stock.changed"


Handler = Callable[[object], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = {}

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: object) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler(event)
