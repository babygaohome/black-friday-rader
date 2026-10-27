import random
from datetime import timedelta

from dealradar.retailers.base import ScanErrorType

# Network errors: 30s, 2min, 10min then give up (no infinite retry).
NETWORK_BACKOFF = (30, 120, 600)

# Not worth retrying soon / at all.
NO_RETRY = {ScanErrorType.PRODUCT_REMOVED, ScanErrorType.PARSE_ERROR, ScanErrorType.INVALID_PRICE}
SLOW_RETRY = {ScanErrorType.RATE_LIMIT: 600, ScanErrorType.CAPTCHA: 1800}


def retry_delay(error: ScanErrorType, attempt: int, rng: random.Random | None = None) -> timedelta | None:
    """Delay before retry number `attempt` (0-based), with +/-20% jitter; None = stop retrying."""
    r = rng or random
    if error in NO_RETRY:
        return None
    if error in SLOW_RETRY:
        base = SLOW_RETRY[error] * (2 ** attempt)
        if attempt >= 3:
            return None
    else:
        if attempt >= len(NETWORK_BACKOFF):
            return None
        base = NETWORK_BACKOFF[attempt]
    return timedelta(seconds=base * r.uniform(0.8, 1.2))
