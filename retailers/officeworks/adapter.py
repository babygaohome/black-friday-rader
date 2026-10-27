from dealradar.retailers.base import RawOffer
from dealradar.retailers.http_adapter import HttpRetailerAdapter
from retailers.officeworks.parser import parse_product


class OfficeworksAdapter(HttpRetailerAdapter):
    code = "officeworks"
    name = "Officeworks"
    domains = ("officeworks.com.au",)

    def parse(self, html: str, url: str) -> RawOffer:
        return parse_product(html, url)
