"""Product matching (M03). Pure functions; persistence lives in dealradar.services.catalog."""
from dataclasses import dataclass
from typing import Iterable

from dealradar.matching.attributes import Attributes, conflicts, extract, norm_code

CONFIDENCE_THRESHOLD = 0.85  # below this, a human reviews the match

GTIN = 1.00
MPN_BRAND = 0.98
BRAND_MODEL_VARIANT = 0.90
FUZZY_MAX = 0.84  # fuzzy evidence alone can never reach auto-accept


@dataclass(frozen=True)
class Candidate:
    """A listing to be matched (from a retailer)."""
    title: str
    brand: str | None = None
    gtin: str | None = None
    mpn: str | None = None


@dataclass(frozen=True)
class ProductRef:
    """A canonical product as the matcher sees it."""
    id: object
    name: str
    brand: str | None = None
    gtin: str | None = None
    mpn: str | None = None


@dataclass(frozen=True)
class MatchResult:
    product_id: object | None
    confidence: float
    method: str  # GTIN | MPN_BRAND | BRAND_MODEL_VARIANT | FUZZY | NONE
    variant_match: bool
    needs_review: bool
    reasons: tuple[str, ...] = ()


NO_MATCH = MatchResult(None, 0.0, "NONE", False, False)


def _models_compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    """True when every model token on one side has a counterpart on the other, allowing a shorthand
    (e.g. 'xm6' vs 'wh1000xm6') where the shorter token is the tail of the longer one."""
    if not a or not b:
        return False
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    for tok in small:
        if not any(tok == other or (len(tok) >= 3 and other.endswith(tok)) for other in big):
            return False
    return True


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def _score(cand: Candidate, cattrs: Attributes, prod: ProductRef) -> MatchResult | None:
    # Level 1: identical GTIN/EAN/UPC (a strong identifier still must not contradict hard attributes? No:
    # identifiers are authoritative, they already encode the exact variant).
    if cand.gtin and prod.gtin and norm_code(cand.gtin) == norm_code(prod.gtin):
        return MatchResult(prod.id, GTIN, "GTIN", True, False, ("gtin equal",))

    pattrs = extract(prod.name, prod.brand)
    same_brand = bool(cattrs.brand) and cattrs.brand == pattrs.brand

    # Level 2: MPN + brand.
    if cand.mpn and prod.mpn and same_brand and norm_code(cand.mpn) == norm_code(prod.mpn):
        return MatchResult(prod.id, MPN_BRAND, "MPN_BRAND", True, False, ("mpn+brand equal",))

    if not same_brand:
        return None
    clash = conflicts(cattrs, pattrs)
    if clash:
        return None  # a different storage/size/colour/generation/variant: never the same product

    # Level 3: brand + model + variant.
    if cattrs.digit_tokens and cattrs.digit_tokens == pattrs.digit_tokens:
        both_known = sum(
            1 for n in ("colour", "storage", "memory", "size")
            if getattr(cattrs, n) is not None and getattr(pattrs, n) is not None
        )
        # A missing attribute on one side (e.g. title omits colour) lowers certainty a little.
        missing = sum(
            1 for n in ("colour", "storage", "memory", "size")
            if (getattr(cattrs, n) is None) != (getattr(pattrs, n) is None)
        )
        conf = BRAND_MODEL_VARIANT - 0.05 * missing
        return MatchResult(prod.id, round(conf, 2), "BRAND_MODEL_VARIANT", missing == 0, conf < CONFIDENCE_THRESHOLD,
                           (f"model tokens equal, {both_known} variant attrs agree, {missing} missing",))

    # Level 4: fuzzy. Only when the model tokens are shorthand-compatible; never auto-accepted.
    if _models_compatible(cattrs.digit_tokens, pattrs.digit_tokens):
        sim = _jaccard(cattrs.words | cattrs.digit_tokens, pattrs.words | pattrs.digit_tokens)
        conf = round(min(FUZZY_MAX, 0.70 + 0.14 * sim), 2)
        return MatchResult(prod.id, conf, "FUZZY", False, True, (f"shorthand model tokens, similarity {sim:.2f}",))
    return None


def match(cand: Candidate, products: Iterable[ProductRef]) -> MatchResult:
    """Best canonical product for a listing, or NO_MATCH. `needs_review` is True when confidence < threshold."""
    cattrs = extract(cand.title, cand.brand)
    best: MatchResult | None = None
    for prod in products:
        res = _score(cand, cattrs, prod)
        if res and (best is None or res.confidence > best.confidence):
            best = res
    if best is None:
        return NO_MATCH
    return MatchResult(best.product_id, best.confidence, best.method, best.variant_match,
                       best.confidence < CONFIDENCE_THRESHOLD, best.reasons)
