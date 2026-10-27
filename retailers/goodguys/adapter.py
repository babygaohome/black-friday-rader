from dealradar.retailers.base import RawOffer
from dealradar.retailers.http_adapter import HttpRetailerAdapter
from retailers.goodguys.parser import parse_product


class GoodGuysAdapter(HttpRetailerAdapter):
    code = "goodguys"
    name = "The Good Guys"
    domains = ("thegoodguys.com.au",)

    def parse(self, html: str, url: str) -> RawOffer:
        return parse_product(html, url)
