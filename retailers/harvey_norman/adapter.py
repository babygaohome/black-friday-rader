from dealradar.retailers.base import RawOffer
from dealradar.retailers.http_adapter import HttpRetailerAdapter
from retailers.harvey_norman.parser import parse_product


class HarveyNormanAdapter(HttpRetailerAdapter):
    code = "harveynorman"
    name = "Harvey Norman"
    domains = ("harveynorman.com.au",)

    def parse(self, html: str, url: str) -> RawOffer:
        return parse_product(html, url)
