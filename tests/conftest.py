import pytest_asyncio

from dealradar.core.db import create_all, make_engine, make_session_factory


@pytest_asyncio.fixture
async def factory(tmp_path):
    # file-backed: several sessions/connections must see the same database
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await create_all(engine)
    yield make_session_factory(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory):
    async with factory() as s:
        yield s
