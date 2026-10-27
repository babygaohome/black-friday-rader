import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from dealradar import models  # noqa: F401  (register tables)
from dealradar.core.config import get_settings
from dealradar.core.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _configure(**kwargs) -> None:
    # batch mode lets ALTERs that SQLite can't do natively work there too (copy-and-move)
    context.configure(target_metadata=target_metadata, render_as_batch=True, compare_type=True, **kwargs)


def run_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = make_engine(_url())
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_run_sync)
            await conn.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
