"""Create products/offers from a user-submitted URL (design doc section 33)."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import Offer, Product, Retailer
from dealradar.normalization.pipeline import NormalizedOffer, normalize_offer
from dealradar.retailers.base import RetailerAdapter
from dealradar.retailers.registry import RetailerRegistry
from dealradar.services.history import record_snapshot


@dataclass
class AddResult:
    product: Product
    offer: Offer
    created: bool


async def _retailer(session: AsyncSession, adapter: RetailerAdapter) -> Retailer:
    r = (await session.execute(select(Retailer).where(Retailer.code == adapter.code))).scalar_one_or_none()
    if r is None:
        r = Retailer(code=adapter.code, name=adapter.name, domain=adapter.domains[0])
        session.add(r)
        await session.flush()
    return r


async def match_or_create_product(session: AsyncSession, norm: NormalizedOffer) -> tuple[Product, float | None]:
    """Placeholder matcher: exact GTIN, then brand+MPN. Anything else becomes its own product.

    The full matching engine (M03: variants, fuzzy match, manual review) replaces this later.
    """
    if norm.gtin:
        p = (await session.execute(select(Product).where(Product.gtin == norm.gtin))).scalars().first()
        if p:
            return p, 1.0
    if norm.mpn and norm.brand:
        p = (
            await session.execute(select(Product).where(Product.mpn == norm.mpn, Product.brand == norm.brand))
        ).scalars().first()
        if p:
            return p, 0.98
    product = Product(brand=norm.brand or "", name=norm.title, gtin=norm.gtin, mpn=norm.mpn)
    session.add(product)
    await session.flush()
    return product, None


async def add_from_url(session: AsyncSession, registry: RetailerRegistry, url: str) -> AddResult:
    adapter = registry.resolve(url)  # raises UnsupportedUrl before any network access
    norm = normalize_offer(await adapter.fetch_product(url))
    retailer = await _retailer(session, adapter)

    offer = (
        await session.execute(select(Offer).where(Offer.retailer_id == retailer.id, Offer.retailer_sku == norm.retailer_sku))
    ).scalar_one_or_none()
    if offer is not None:
        product = await session.get(Product, offer.product_id)
        return AddResult(product, offer, created=False)

    product, confidence = await match_or_create_product(session, norm)
    offer = Offer(
        product_id=product.id, retailer_id=retailer.id, retailer_sku=norm.retailer_sku, url=url, title=norm.title,
        match_confidence=confidence, currency=norm.currency, current_price=norm.price.item_price,
        current_effective_price=norm.effective_price, original_price=norm.price.original_price,
        stock_status=norm.stock,
    )
    session.add(offer)
    await session.flush()
    await record_snapshot(
        session, offer.id, norm.price.item_price, norm.effective_price, norm.price.original_price, norm.stock,
        flagged=norm.validation.flagged,
    )
    return AddResult(product, offer, created=True)
