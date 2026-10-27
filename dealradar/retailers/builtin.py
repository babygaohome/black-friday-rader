"""The retailers shipped with DealRadar. Adding a retailer = add its adapter here."""
from dealradar.retailers.registry import RetailerRegistry


def build_default_registry() -> RetailerRegistry:
    from retailers.jbhifi.adapter import JBHiFiAdapter

    registry = RetailerRegistry()
    for adapter in (JBHiFiAdapter(),):
        registry.register(adapter)
    return registry
