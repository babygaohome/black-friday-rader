import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dealradar.core.db import Base
from dealradar.models.enums import AlertType, NotificationStatus, Priority, StockStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---- M01 User ----
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Australia/Sydney")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")

    preferences: Mapped["UserPreference"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    default_alert_channel: Mapped[str] = mapped_column(String(20), default="telegram")
    default_cooldown_minutes: Mapped[int] = mapped_column(Integer, default=10)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="preferences")


# ---- M02 Canonical Product ----
class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    brand: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(500))
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(14), index=True, nullable=True)
    ean: Mapped[str | None] = mapped_column(String(14), nullable=True)
    upc: Mapped[str | None] = mapped_column(String(14), nullable=True)
    mpn: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    variant_signature: Mapped[str | None] = mapped_column(String(300), nullable=True)

    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    offers: Mapped[list["Offer"]] = relationship(back_populates="product")


class ProductVariant(Base):
    __tablename__ = "product_variants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    colour: Mapped[str | None] = mapped_column(String(50), nullable=True)
    storage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    memory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    variant_key: Mapped[str] = mapped_column(String(300), unique=True)

    product: Mapped[Product] = relationship(back_populates="variants")


# ---- Retailer / Offer ----
class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(50), unique=True)  # jbhifi, amazon_au, ...
    name: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Offer(TimestampMixin, Base):
    """A retailer listing of a canonical product (kept separate per design principle 1)."""

    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("retailer_id", "retailer_sku", name="uq_offer_retailer_sku"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), index=True, nullable=True)
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    retailer_sku: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500))
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    current_effective_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    stock_status: Mapped[StockStatus] = mapped_column(Enum(StockStatus), default=StockStatus.UNKNOWN)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[Product | None] = relationship(back_populates="offers")
    retailer: Mapped[Retailer] = relationship()


# ---- M10 Price History ----
class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (Index("ix_price_history_offer_ts", "offer_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    effective_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    stock_status: Mapped[StockStatus] = mapped_column(Enum(StockStatus), default=StockStatus.UNKNOWN)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # suspicious price, never triggers alerts
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---- M11 Watchlist ----
class WatchItem(Base):
    __tablename__ = "watch_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_watch_user_product"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    minimum_discount: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)  # percent
    notify_on_stock: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_on_historical_low: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.NORMAL)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    product: Mapped[Product] = relationship()


# ---- Alerts / Notifications / Ops (consumed by modules D and E) ----
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    type: Mapped[AlertType] = mapped_column(Enum(AlertType))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    watch_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("watch_items.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    deal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    alert_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.PENDING)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RetailerHealth(Base):
    __tablename__ = "retailer_health"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id", ondelete="CASCADE"), primary_key=True)
    success_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1"))
    error_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    captcha_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ONLINE")  # ONLINE | DEGRADED | OFFLINE
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    watch_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("watch_items.id", ondelete="CASCADE"), index=True)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
