from urllib.parse import urlparse

from dealradar.retailers.base import RetailerAdapter, UnsupportedUrl


class RetailerRegistry:
    """Domain allowlist + retailer resolver. User-supplied URLs must resolve here before any request."""

    def __init__(self) -> None:
        self._adapters: dict[str, RetailerAdapter] = {}

    def register(self, adapter: RetailerAdapter) -> None:
        self._adapters[adapter.code] = adapter

    def get(self, code: str) -> RetailerAdapter:
        return self._adapters[code]

    def codes(self) -> list[str]:
        return sorted(self._adapters)

    def resolve(self, url: str) -> RetailerAdapter:
        parsed = urlparse(url.strip())
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise UnsupportedUrl("only plain https product URLs are accepted")
        if parsed.port not in (None, 443):
            raise UnsupportedUrl("custom ports are not allowed")
        for adapter in self._adapters.values():
            if adapter.owns_url(url):
                return adapter
        raise UnsupportedUrl(f"domain not allowlisted: {parsed.hostname}")
