from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Sequence

SUSPICIOUS_RATIO = Decimal("0.2")  # < 20% of historical median is treated as a likely parse error


@dataclass(frozen=True)
class ValidationResult:
    valid: bool  # False => reject outright (non-positive price)
    flagged: bool  # True => store but never trigger alerts
    reason: str | None = None


def validate_price(effective_price: Decimal | None, history: Sequence[Decimal] = ()) -> ValidationResult:
    if effective_price is None or effective_price <= 0:
        return ValidationResult(False, False, "non_positive_price")
    if history:
        med = Decimal(str(median(history)))
        if med > 0 and effective_price < med * SUSPICIOUS_RATIO:
            return ValidationResult(True, True, "below_20pct_of_median")
    return ValidationResult(True, False)
