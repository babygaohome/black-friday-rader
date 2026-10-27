import re

from dealradar.models.enums import StockStatus

# Order matters: more specific / negative phrases first.
_RULES: list[tuple[re.Pattern[str], StockStatus]] = [
    (re.compile(r"out[\s_-]*of[\s_-]*stock|sold[\s_-]*out|unavailable|currently unavailable|no longer available", re.I), StockStatus.OUT_OF_STOCK),
    (re.compile(r"pre[\s_-]*order|presale|pre[\s_-]*sale", re.I), StockStatus.PREORDER),
    (re.compile(r"back[\s_-]*order|backordered", re.I), StockStatus.BACKORDER),
    (re.compile(r"low[\s_-]*stock|limited[\s_-]*stock|only \d+ (left|remaining)|few left|last (few|one)", re.I), StockStatus.LOW_STOCK),
    (re.compile(r"in[\s_-]*stock|available( now)?|online only|ready to ship|ships? (today|within)|add to cart|buy now", re.I), StockStatus.IN_STOCK),
]


def normalize_stock(raw: str | None) -> StockStatus:
    """Map retailer wording (or schema.org availability URLs) to the unified status; never raises."""
    if not raw:
        return StockStatus.UNKNOWN
    text = raw.rsplit("/", 1)[-1] if raw.startswith("http") else raw  # schema.org/InStock -> InStock
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # InStock -> In Stock
    for pattern, status in _RULES:
        if pattern.search(text):
            return status
    return StockStatus.UNKNOWN
