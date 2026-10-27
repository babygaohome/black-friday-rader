"""ASGI entry point: `uvicorn dealradar.main:app`."""
import redis.asyncio as aioredis

from dealradar.admin_ops import celery_worker_stats, redis_queue_stats
from dealradar.api.app import create_app
from dealradar.core.config import get_settings
from dealradar.core.db import make_engine, make_session_factory
from dealradar.observability.logs import configure_logging
from dealradar.realtime.hub import run_redis_relay
from dealradar.retailers.builtin import build_default_registry
from dealradar.scanning.tasks import celery_app

_settings = get_settings()
configure_logging("api", _settings.log_level)
_redis = aioredis.from_url(_settings.redis_url)


async def _relay(hub):
    await run_redis_relay(aioredis.from_url(_settings.redis_url), hub)


app = create_app(
    make_session_factory(make_engine(_settings.database_url)),
    build_default_registry(),
    _settings.secret_key,
    _settings.token_ttl_seconds,
    relay=_relay,
    queue_stats=redis_queue_stats(_redis),
    worker_stats=celery_worker_stats(celery_app),
)
