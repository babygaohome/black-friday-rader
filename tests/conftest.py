import pytest_asyncio

from dealradar.core.db import create_all, make_engine, make_session_factory


@pytest_asyncio.fixture
async def session():
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()
