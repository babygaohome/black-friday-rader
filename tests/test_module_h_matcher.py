import pytest

from dealradar.matching.attributes import extract, variant_key
from dealradar.matching.matcher import CONFIDENCE_THRESHOLD, Candidate, ProductRef, match

XM6 = ProductRef("xm6", "Sony WH-1000XM6 Wireless Headphones Black", "Sony", mpn="WH1000XM6B")
IP17_256 = ProductRef("ip256", "Apple iPhone 17 256GB Black", "Apple")
IP17_512 = ProductRef("ip512", "Apple iPhone 17 512GB Black", "Apple")
IP17_PRO = ProductRef("ippro", "Apple iPhone 17 Pro 256GB Black", "Apple")
MBA = ProductRef("mba", "Apple MacBook Air 13-inch M5 16GB 512GB Silver", "Apple")
ALL = [XM6, IP17_256, IP17_512, IP17_PRO, MBA]


def test_extract_attributes():
    a = extract("Apple MacBook Air 13-inch M5 16GB 512GB Space Grey", "Apple")
    assert (a.memory, a.storage, a.size, a.colour) == ("16gb", "512gb", "13", "grey")
    assert "m5" in a.digit_tokens and "air" in a.variant_words
    b = extract("Sony WH-1000XM6 Wireless Noise Cancelling Headphones - Black", "Sony")
    assert b.digit_tokens == {"wh1000xm6"} and b.colour == "black" and b.storage is None
    assert extract("Galaxy S25 1TB Gray").storage == "1tb" and extract("x gray").colour == "grey"
    assert extract("Mouse 27\" monitor").size == "27"


def test_variant_key():
    k = variant_key("Sony", extract("Sony WH-1000XM6 Black", "Sony"), "WH-1000XM6")
    assert k == "sony-wh1000xm6-black"


def test_design_doc_three_retailers_same_product():
    for title in ["Sony WH1000XM6/B", "Sony WH-1000XM6 Wireless Headphones Black",
                  "Sony WH-1000XM6 Noise Cancelling Headphones - Black"]:
        r = match(Candidate(title, "Sony"), ALL)
        assert r.product_id == "xm6", title
        assert not r.needs_review or title == "Sony WH1000XM6/B"


def test_storage_never_matches_across_capacities():
    r = match(Candidate("iPhone 17 512GB Black", "Apple"), [IP17_256])
    assert r.product_id is None
    assert match(Candidate("Apple iPhone 17 256GB Black", "Apple"), ALL).product_id == "ip256"
    assert match(Candidate("Apple iPhone 17 512GB Black", "Apple"), ALL).product_id == "ip512"


def test_pro_is_not_base_model_and_colour_conflict():
    assert match(Candidate("Apple iPhone 17 Pro 256GB Black", "Apple"), ALL).product_id == "ippro"
    assert match(Candidate("Apple iPhone 17 Pro 256GB Black", "Apple"), [IP17_256]).product_id is None
    assert match(Candidate("Apple iPhone 17 256GB White", "Apple"), [IP17_256]).product_id is None


def test_generation_and_size_conflicts():
    xm5 = Candidate("Sony WH-1000XM5 Headphones Black", "Sony")
    assert match(xm5, [XM6]).product_id is None
    mba15 = Candidate("Apple MacBook Air 15-inch M5 16GB 512GB Silver", "Apple")
    assert match(mba15, [MBA]).product_id is None
    assert match(Candidate("Apple MacBook Air 13-inch M5 16GB 256GB Silver", "Apple"), [MBA]).product_id is None


def test_gtin_and_mpn_are_authoritative():
    gt = ProductRef("g", "Completely different title", "Sony", gtin="4548736145871")
    r = match(Candidate("Whatever", "Sony", gtin="4548736145871"), [gt])
    assert (r.product_id, r.confidence, r.method) == ("g", 1.0, "GTIN")
    r = match(Candidate("Sony cans", "Sony", mpn="wh-1000xm6/b"), [XM6])
    assert (r.method, r.confidence) == ("MPN_BRAND", 0.98)
    # MPN equal but a different brand string must not match
    assert match(Candidate("x", "Bose", mpn="WH1000XM6B"), [XM6]).product_id is None


def test_brand_must_agree():
    assert match(Candidate("Samsung iPhone 17 256GB Black", "Samsung"), [IP17_256]).product_id is None


def test_missing_attribute_lowers_confidence_but_can_still_match():
    r = match(Candidate("Sony WH-1000XM6 Headphones", "Sony"), [XM6])  # no colour in title
    assert r.product_id == "xm6" and r.confidence == 0.85 and not r.variant_match and not r.needs_review


def test_shorthand_goes_to_manual_review_not_auto():
    r = match(Candidate("Sony XM6 Headphones Black", "Sony"), [XM6])
    assert r.product_id == "xm6" and r.method == "FUZZY" and r.needs_review and r.confidence < CONFIDENCE_THRESHOLD


def test_no_candidates_and_brandless_titles():
    assert match(Candidate("Sony WH-1000XM6", "Sony"), []).product_id is None
    r = match(Candidate("Sony WH-1000XM6 Black"), [XM6])  # brand inferred from the first word
    assert r.product_id == "xm6"


@pytest.mark.parametrize("a,b", [
    ("Apple iPhone 17 256GB Black", "Apple iPhone 17 256GB Black"),
    ("Apple iPhone 17 256 GB Black", "Apple iPhone 17 256GB Black"),
])
def test_formatting_noise_is_ignored(a, b):
    assert match(Candidate(a, "Apple"), [ProductRef("p", b, "Apple")]).confidence >= 0.9
