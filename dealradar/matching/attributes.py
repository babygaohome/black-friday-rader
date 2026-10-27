"""Attribute extraction from retailer titles (M03).

Hard attributes (storage, memory, screen size, colour, model signature) are
extracted deterministically; they may never be overridden by fuzzy similarity.
"""
import re
from dataclasses import dataclass, field

_CAPACITY = re.compile(r"(?<![\w.])(\d{1,4})\s?(gb|tb)\b", re.I)
_SIZE = re.compile(r"(?<![\w.])(\d{1,2}(?:\.\d)?)\s?(?:-?\s?inch(?:es)?|\"|”|in\b)", re.I)
_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.I)  # "/" separates (WH1000XM6/B = model + colour code)

COLOURS = {
    "black", "white", "silver", "grey", "gray", "blue", "red", "green", "pink", "purple", "gold", "midnight",
    "starlight", "graphite", "titanium", "natural", "cream", "orange", "yellow", "beige", "navy", "teal",
    "lavender", "rose", "bronze", "copper", "ivory", "charcoal",
}
_COLOUR_ALIASES = {"gray": "grey"}

# Words that distinguish products of the same family (iPhone 17 vs iPhone 17 Pro).
VARIANT_WORDS = {
    "pro", "max", "plus", "ultra", "mini", "lite", "se", "fe", "xl", "air", "digital", "disc", "slim", "oled",
    "gaming", "elite", "neo", "edge", "flip", "fold", "studio", "prime",
}

STOP_WORDS = {
    "the", "and", "with", "for", "new", "wireless", "bluetooth", "headphones", "headphone", "earbuds", "noise",
    "cancelling", "canceling", "smartphone", "phone", "laptop", "notebook", "tablet", "console", "tv", "television",
    "smart", "mouse", "keyboard", "inch", "gb", "tb", "au", "australia", "version", "model", "edition", "unlocked",
    "over", "ear", "in", "of", "a", "an",
}


@dataclass(frozen=True)
class Attributes:
    brand: str = ""
    colour: str | None = None
    storage: str | None = None  # "256gb"
    memory: str | None = None  # "16gb"
    size: str | None = None  # "13"
    digit_tokens: frozenset[str] = frozenset()  # normalized tokens containing digits, e.g. {"wh1000xm6"}
    variant_words: frozenset[str] = frozenset()
    words: frozenset[str] = field(default_factory=frozenset)  # remaining descriptive words (for fuzzy scoring)


def norm_code(value: str | None) -> str:
    """'WH-1000XM6/B' -> 'wh1000xm6b'."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _capacity_value(n: str, unit: str) -> str:
    return f"{int(n)}{unit.lower()}"


def _gb(v: str) -> int:
    return int(v[:-2]) * (1024 if v.endswith("tb") else 1)


def extract(title: str, brand: str | None = None) -> Attributes:
    text = (title or "").lower()
    brand_n = (brand or "").strip().lower()
    tokens_all = _TOKEN.findall(text)

    # Capacities: with two values the smaller is memory and the larger is storage (e.g. "16GB 512GB").
    caps = sorted({_capacity_value(n, u) for n, u in _CAPACITY.findall(text)}, key=_gb)
    memory = storage = None
    if len(caps) == 1:
        storage = caps[0]
    elif len(caps) >= 2:
        memory, storage = caps[0], caps[-1]

    m = _SIZE.search(text)
    size = str(float(m.group(1))).rstrip("0").rstrip(".") if m else None
    # Remove capacity / size phrases so their numbers don't become model tokens ("256 GB", "13-inch").
    text = _SIZE.sub(" ", _CAPACITY.sub(" ", text))
    tokens = _TOKEN.findall(text)
    if not brand_n and tokens_all:
        brand_n = tokens_all[0]

    colour = None
    for tok in tokens:
        if tok in COLOURS:
            colour = _COLOUR_ALIASES.get(tok, tok)
            break

    digit_tokens: set[str] = set()
    variant_words: set[str] = set()
    words: set[str] = set()
    brand_tokens = set(re.findall(r"[a-z0-9]+", brand_n))
    for tok in tokens:
        flat = norm_code(tok)
        if not flat or flat in brand_tokens or tok in COLOURS or tok in STOP_WORDS:
            continue
        if len(flat) == 1 and flat.isalpha():
            continue  # stray letters such as the "B" in WH1000XM6/B
        if flat in VARIANT_WORDS:
            variant_words.add(flat)
        elif any(ch.isdigit() for ch in flat):
            digit_tokens.add(flat)
        else:
            words.add(flat)
    return Attributes(brand_n, colour, storage, memory, size, frozenset(digit_tokens), frozenset(variant_words), frozenset(words))


def conflicts(a: Attributes, b: Attributes) -> list[str]:
    """Hard attribute disagreements; any entry means these are different products."""
    out = []
    for name in ("storage", "memory", "size", "colour"):
        va, vb = getattr(a, name), getattr(b, name)
        if va is not None and vb is not None and va != vb:
            out.append(name)
    if a.variant_words != b.variant_words:
        out.append("variant")
    return out


def variant_key(brand: str, attrs: Attributes, model: str = "") -> str:
    parts = [norm_code(brand) or attrs.brand, norm_code(model) or "-".join(sorted(attrs.digit_tokens | attrs.variant_words)),
             attrs.colour, attrs.memory, attrs.storage, attrs.size and f"{attrs.size}in"]
    return "-".join(p for p in parts if p)
