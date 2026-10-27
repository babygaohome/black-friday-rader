import os

import pytest_asyncio

from dealradar.core.db import Base, create_all, make_engine, make_session_factory


@pytest_asyncio.fixture
async def factory(tmp_path):
    # Default: file-backed SQLite (several sessions/connections must see the same database).
    # DEALRADAR_TEST_DATABASE_URL=postgresql+asyncpg://... runs the same suite against PostgreSQL;
    # every test then starts from freshly created tables.
    url = os.environ.get("DEALRADAR_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(url)
    if not url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await create_all(engine)
    yield make_session_factory(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory):
    async with factory() as s:
        yield s
