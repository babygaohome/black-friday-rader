"""ASGI entry point: `uvicorn dealradar.main:app`."""
from dealradar.api.app import create_app
from dealradar.core.config import get_settings
from dealradar.core.db import make_engine, make_session_factory
from dealradar.retailers.builtin import build_default_registry

_settings = get_settings()
app = create_app(
    make_session_factory(make_engine(_settings.database_url)),
    build_default_registry(),
    _settings.secret_key,
    _settings.token_ttl_seconds,
)
