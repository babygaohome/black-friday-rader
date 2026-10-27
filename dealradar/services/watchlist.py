import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import Priority, WatchItem


async def add_watch(
    session: AsyncSession,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    target_price: Decimal | None = None,
    minimum_discount: Decimal | None = None,
    notify_on_stock: bool = False,
    notify_on_historical_low: bool = False,
    priority: Priority = Priority.NORMAL,
) -> WatchItem:
    """Create a watch item, or update the existing one for (user, product)."""
    item = (
        await session.execute(select(WatchItem).where(WatchItem.user_id == user_id, WatchItem.product_id == product_id))
    ).scalar_one_or_none()
    if item is None:
        item = WatchItem(user_id=user_id, product_id=product_id)
        session.add(item)
    item.target_price = target_price
    item.minimum_discount = minimum_discount
    item.notify_on_stock = notify_on_stock
    item.notify_on_historical_low = notify_on_historical_low
    item.priority = priority
    item.active = True
    await session.flush()
    return item


async def list_watches(session: AsyncSession, user_id: uuid.UUID, active_only: bool = True) -> list[WatchItem]:
    stmt = select(WatchItem).where(WatchItem.user_id == user_id)
    if active_only:
        stmt = stmt.where(WatchItem.active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def watchers_of_product(session: AsyncSession, product_id: uuid.UUID) -> list[WatchItem]:
    """Active watch items on a product (used by the alert engine)."""
    stmt = select(WatchItem).where(WatchItem.product_id == product_id, WatchItem.active.is_(True))
    return list((await session.execute(stmt)).scalars())


async def deactivate_watch(session: AsyncSession, user_id: uuid.UUID, watch_id: uuid.UUID) -> bool:
    item = await session.get(WatchItem, watch_id)
    if item is None or item.user_id != user_id:
        return False
    item.active = False
    await session.flush()
    return True
