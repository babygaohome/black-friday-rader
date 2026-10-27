import enum


class StockStatus(str, enum.Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    PREORDER = "PREORDER"
    BACKORDER = "BACKORDER"
    UNKNOWN = "UNKNOWN"


class Priority(str, enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertType(str, enum.Enum):
    TARGET_PRICE_HIT = "TARGET_PRICE_HIT"
    PRICE_DROP = "PRICE_DROP"
    HISTORICAL_LOW = "HISTORICAL_LOW"
    RESTOCK = "RESTOCK"
    LOW_STOCK = "LOW_STOCK"
    FLASH_DEAL = "FLASH_DEAL"


class NotificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRY = "RETRY"
