import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_CENT = Decimal("0.01")


def parse_money(value: Decimal | str | float | int | None) -> Decimal | None:
    """'$1,299.00', 'A$399', 399, '399.5' -> Decimal; None/garbage -> None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, (int, float)):
        d = Decimal(str(value))
    else:
        cleaned = re.sub(r"[^\d.,-]", "", value)
        if not cleaned:
            return None
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            head, _, tail = cleaned.rpartition(",")
            cleaned = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else cleaned.replace(",", "")
        try:
            d = Decimal(cleaned)
        except InvalidOperation:
            return None
    return d.quantize(_CENT)


@dataclass(frozen=True)
class PriceBreakdown:
    item_price: Decimal
    shipping: Decimal
    coupon: Decimal
    effective_price: Decimal
    original_price: Decimal | None

    @property
    def retailer_discount_pct(self) -> Decimal | None:
        """Discount vs the retailer's own RRP, e.g. 549 -> 419 = 23.69."""
        if self.original_price and self.original_price > 0 and self.item_price < self.original_price:
            return ((self.original_price - self.item_price) / self.original_price * 100).quantize(_CENT)
        return None


def build_breakdown(price, original_price=None, coupon=None, shipping=None) -> PriceBreakdown | None:
    """effective_price = item_price - coupon + shipping (never below 0). None if price is unusable."""
    item = parse_money(price)
    if item is None or item <= 0:
        return None
    ship = max(parse_money(shipping) or Decimal("0.00"), Decimal("0.00"))
    off = max(parse_money(coupon) or Decimal("0.00"), Decimal("0.00"))
    orig = parse_money(original_price)
    if orig is not None and orig <= 0:
        orig = None
    effective = max(item - off + ship, Decimal("0.00")).quantize(_CENT)
    return PriceBreakdown(item, ship, off, effective, orig)
