"""The retailers shipped with DealRadar. Adding a retailer = add its adapter here."""
from dealradar.retailers.registry import RetailerRegistry


def build_default_registry() -> RetailerRegistry:
    from retailers.jbhifi.adapter import JBHiFiAdapter
    from retailers.goodguys.adapter import GoodGuysAdapter
    from retailers.harvey_norman.adapter import HarveyNormanAdapter
    from retailers.officeworks.adapter import OfficeworksAdapter

    registry = RetailerRegistry()
    for adapter in (JBHiFiAdapter(), OfficeworksAdapter(), GoodGuysAdapter(), HarveyNormanAdapter(),):
        registry.register(adapter)
    return registry
