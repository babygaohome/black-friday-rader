"""The retailers shipped with DealRadar. Adding a retailer = add its adapter here."""
from dealradar.retailers.registry import RetailerRegistry


def build_default_registry(settings=None) -> RetailerRegistry:
    from retailers.jbhifi.adapter import JBHiFiAdapter
    from retailers.goodguys.adapter import GoodGuysAdapter
    from retailers.harvey_norman.adapter import HarveyNormanAdapter
    from retailers.officeworks.adapter import OfficeworksAdapter

    registry = RetailerRegistry()
    for adapter in (JBHiFiAdapter(), OfficeworksAdapter(), GoodGuysAdapter(), HarveyNormanAdapter(),):
        registry.register(adapter)

    # Amazon AU uses the official Product Advertising API, so it needs Associates credentials.
    from dealradar.core.config import get_settings

    settings = settings or get_settings()
    if settings.amazon_paapi_access_key and settings.amazon_paapi_secret_key and settings.amazon_paapi_partner_tag:
        from retailers.amazon_au.adapter import AmazonAUAdapter

        registry.register(AmazonAUAdapter(
            settings.amazon_paapi_access_key, settings.amazon_paapi_secret_key, settings.amazon_paapi_partner_tag))
    return registry
