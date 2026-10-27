"""Keyword-based product categories. Retailers' own breadcrumbs differ per site, so the product name is the
common denominator. The first matching rule wins, so more specific rules come first."""
import re

CATEGORIES: dict[str, str] = {
    "phones": "Phones",
    "tablets": "Tablets",
    "laptops": "Laptops",
    "computers": "Computers & monitors",
    "tv": "TVs & projectors",
    "audio": "Audio & headphones",
    "cameras": "Cameras",
    "gaming": "Gaming",
    "wearables": "Wearables",
    "appliances": "Home appliances",
    "networking": "Networking",
    "storage": "Storage",
    "other": "Other",
}

# (category, pattern) - patterns match whole words, case-insensitive
_RULES: list[tuple[str, str]] = [
    ("gaming", r"playstation|ps[45]\b|xbox|nintendo|switch (oled|lite|console)|steam deck|gaming (mouse|keyboard|headset|chair)|controller"),
    ("wearables", r"smart ?watch|apple watch|galaxy watch|fitbit|garmin|fitness (band|tracker)|watch (series|ultra|se)\b"),
    ("tablets", r"\bipad\b|tablet|galaxy tab|kindle"),
    ("phones", r"iphone|smartphone|galaxy (s|a|z)\d|pixel \d|\bphone\b|oppo|moto g"),
    ("laptops", r"laptop|macbook|notebook|chromebook|thinkpad|zenbook|ideapad|surface (laptop|pro)"),
    ("tv", r"\btv\b|television|oled|qled|projector|soundbar"),
    ("cameras", r"camera|gopro|dslr|mirrorless|lens\b|drone|dji"),
    ("audio", r"headphone|earbuds?|earphones?|airpods|speaker|wh-?1000|buds|turntable|amplifier|\bdac\b"),
    ("networking", r"router|wi-?fi|mesh|modem|access point|ethernet"),
    ("storage", r"\bssd\b|hard drive|\bhdd\b|usb (flash )?drive|memory card|microsd|nas\b"),
    ("computers", r"monitor|desktop|\bpc\b|imac|mac mini|keyboard|mouse|printer|graphics card|gpu"),
    ("appliances", r"fridge|refrigerator|washing machine|washer|dryer|dishwasher|vacuum|dyson|air ?fryer|microwave|coffee machine|robot vacuum|oven|cooktop|air conditioner"),
]
_COMPILED = [(c, re.compile(p, re.I)) for c, p in _RULES]


def classify(name: str, brand: str = "") -> str:
    text = f"{brand} {name}"
    for category, pattern in _COMPILED:
        if pattern.search(text):
            return category
    return "other"
