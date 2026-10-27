"""Create products/offers from a user-submitted URL (design doc section 33)."""
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.matching.attributes import extract, variant_key
from dealradar.matching.matcher import Candidate, MatchResult, ProductRef, match
from dealradar.models import MatchReview, Offer, Product, ProductVariant, Retailer
from dealradar.normalization.category import classify
from dealradar.normalization.pipeline import NormalizedOffer, normalize_offer
from dealradar.retailers.base import RetailerAdapter
from dealradar.retailers.registry import RetailerRegistry
from dealradar.services.history import record_snapshot


@dataclass
class AddResult:
    product: Product
    offer: Offer
    created: bool
    needs_review: bool = False


async def _retailer(session: AsyncSession, adapter: RetailerAdapter) -> Retailer:
    r = (await session.execute(select(Retailer).where(Retailer.code == adapter.code))).scalar_one_or_none()
    if r is None:
        r = Retailer(code=adapter.code, name=adapter.name, domain=adapter.domains[0])
        session.add(r)
        await session.flush()
    return r


async def _candidates(session: AsyncSession, norm: NormalizedOffer) -> list[Product]:
    conds = []
    if norm.gtin:
        conds.append(Product.gtin == norm.gtin)
    if norm.mpn:
        conds.append(Product.mpn == norm.mpn)
    brand = (norm.brand or "").strip().lower() or norm.title.split(" ", 1)[0].lower()
    conds.append(func.lower(Product.brand) == brand)
    return list((await session.execute(select(Product).where(or_(*conds)))).scalars())


async def match_or_create_product(
    session: AsyncSession, norm: NormalizedOffer
) -> tuple[Product, float | None, MatchResult]:
    """Attach to an existing canonical product when the matcher is confident, otherwise create one.

    Low-confidence candidates still get their own product (so the user can watch it right away); the caller
    records a MatchReview so a human can later merge it.
    """
    products = {p.id: p for p in await _candidates(session, norm)}
    refs = [ProductRef(p.id, p.name, p.brand, p.gtin, p.mpn) for p in products.values()]
    result = match(Candidate(norm.title, norm.brand, norm.gtin, norm.mpn), refs)
    if result.product_id is not None and not result.needs_review:
        return products[result.product_id], result.confidence, result

    attrs = extract(norm.title, norm.brand)
    key = variant_key(norm.brand or attrs.brand, attrs, norm.mpn or "")
    product = Product(brand=norm.brand or "", name=norm.title, gtin=norm.gtin, mpn=norm.mpn, variant_signature=key or None,
                      category=classify(norm.title, norm.brand or ""))
    session.add(product)
    await session.flush()
    if key and (await session.execute(select(ProductVariant.id).where(ProductVariant.variant_key == key))).first() is None:
        session.add(ProductVariant(product_id=product.id, colour=attrs.colour, storage=attrs.storage, size=attrs.size,
                                   memory=attrs.memory, variant_key=key))
        await session.flush()
    return product, None, result


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

    product, confidence, result = await match_or_create_product(session, norm)
    offer = Offer(
        product_id=product.id, retailer_id=retailer.id, retailer_sku=norm.retailer_sku, url=url, title=norm.title,
        match_confidence=confidence, currency=norm.currency, current_price=norm.price.item_price,
        current_effective_price=norm.effective_price, original_price=norm.price.original_price,
        stock_status=norm.stock,
    )
    session.add(offer)
    await session.flush()
    if result.product_id is not None and result.needs_review:
        session.add(MatchReview(
            offer_id=offer.id, product_id=product.id, suggested_product_id=result.product_id,
            confidence=Decimal(str(result.confidence)), method=result.method,
        ))
    await record_snapshot(
        session, offer.id, norm.price.item_price, norm.effective_price, norm.price.original_price, norm.stock,
        flagged=norm.validation.flagged,
    )
    return AddResult(product, offer, created=True, needs_review=result.product_id is not None and result.needs_review)
