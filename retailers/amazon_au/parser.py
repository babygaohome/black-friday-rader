"""Parse a Product Advertising API 5.0 GetItems response into a RawOffer."""
import re
from typing import Any

from dealradar.retailers.base import RawOffer, ScanError, ScanErrorType

RETAILER = "amazon_au"
_ASIN_IN_URL = re.compile(r"/(?:dp|gp/product|gp/aw/d|exec/obidos/ASIN)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)

# PA-API availability.Type values -> wording understood by normalize_stock()
_AVAILABILITY = {"Now": "In stock", "Backorder": "Backorder", "Preorder": "Pre-order", "Unavailable": "Out of stock"}


def asin_from_url(url: str) -> str | None:
    m = _ASIN_IN_URL.search(url)
    return m.group(1).upper() if m else None


def _get(d: Any, *path):
    for key in path:
        if isinstance(d, dict):
            d = d.get(key)
        elif isinstance(d, list) and isinstance(key, int) and len(d) > key:
            d = d[key]
        else:
            return None
    return d


def parse_get_items(data: dict, asin: str, url: str) -> RawOffer:
    errors = data.get("Errors") or []
    for err in errors:
        code = str(err.get("Code", ""))
        if "TooManyRequests" in code:
            raise ScanError(ScanErrorType.RATE_LIMIT, code)
        if code in ("ItemNotAccessible", "InvalidParameterValue"):
            raise ScanError(ScanErrorType.PRODUCT_REMOVED, code)
    items = _get(data, "ItemsResult", "Items") or []
    item = next((i for i in items if i.get("ASIN") == asin), None)
    if item is None:
        if errors:
            raise ScanError(ScanErrorType.UNKNOWN, str(errors[0].get("Code", "error")))
        raise ScanError(ScanErrorType.PRODUCT_REMOVED, f"{asin} not returned")

    listing = _get(item, "Offers", "Listings", 0)
    if listing is None:
        # Item exists but nobody sells it right now.
        raise ScanError(ScanErrorType.PRODUCT_REMOVED, "no offer listings")
    price = _get(listing, "Price", "Amount")
    if price is None:
        raise ScanError(ScanErrorType.PARSE_ERROR, "listing without price")

    ean = _get(item, "ItemInfo", "ExternalIds", "EANs", "DisplayValues", 0)
    return RawOffer(
        retailer=RETAILER,
        retailer_sku=asin,
        title=str(_get(item, "ItemInfo", "Title", "DisplayValue") or "").strip(),
        url=item.get("DetailPageURL") or url,
        price=price,
        original_price=_get(listing, "SavingBasis", "Amount"),
        currency=_get(listing, "Price", "Currency") or "AUD",
        availability=_AVAILABILITY.get(_get(listing, "Availability", "Type"), _get(listing, "Availability", "Message")),
        seller=_get(listing, "MerchantInfo", "Name"),
        gtin=str(ean) if ean else None,
        mpn=_get(item, "ItemInfo", "ManufactureInfo", "Model", "DisplayValue"),
        brand=_get(item, "ItemInfo", "ByLineInfo", "Brand", "DisplayValue"),
    )
