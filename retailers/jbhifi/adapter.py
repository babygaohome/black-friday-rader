from dealradar.retailers.base import RawOffer
from dealradar.retailers.http_adapter import USER_AGENT, Fetcher, HttpRetailerAdapter  # noqa: F401
from retailers.jbhifi.parser import parse_product


class JBHiFiAdapter(HttpRetailerAdapter):
    code = "jbhifi"
    name = "JB Hi-Fi"
    domains = ("jbhifi.com.au",)

    def parse(self, html: str, url: str) -> RawOffer:
        return parse_product(html, url)
