"""Alembic migrations: they must build exactly the schema the models describe, round-trip, and adopt databases
made by the old create_all-based init-db. Runs on SQLite, or on PostgreSQL with DEALRADAR_TEST_DATABASE_URL."""
import asyncio
import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from dealradar import cli, migrations
from dealradar.core.db import Base, create_all, make_engine


@pytest.fixture
def url(tmp_path):
    url = os.environ.get("DEALRADAR_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'mig.db'}"
    asyncio.run(_reset(url))
    yield url
    asyncio.run(_reset(url))


def _drop_everything(conn):
    Base.metadata.drop_all(conn)  # also drops the PostgreSQL enum types
    conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


async def _run(url, fn):
    engine = make_engine(url)
    try:
        async with engine.begin() as conn:
            return await conn.run_sync(fn)
    finally:
        await engine.dispose()


async def _reset(url):
    await _run(url, _drop_everything)


def _diff(url):
    return asyncio.run(_run(url, lambda conn: compare_metadata(MigrationContext.configure(conn), Base.metadata)))


def _tables(url):
    return set(asyncio.run(_run(url, lambda conn: inspect(conn).get_table_names())))


def _version(url):
    return asyncio.run(_run(url, lambda conn: conn.execute(text("SELECT version_num FROM alembic_version")).scalar()))


def _drop_category(conn):
    conn.execute(text("DROP INDEX ix_products_category"))
    conn.execute(text("ALTER TABLE products DROP COLUMN category"))


def test_upgrade_builds_the_model_schema(url):
    assert migrations.upgrade(url) is None
    assert _diff(url) == []
    assert _version(url) == migrations.PRODUCT_CATEGORY
    assert migrations.upgrade(url) is None  # already at head: no-op
    assert _diff(url) == []


def test_downgrade_to_base_and_back(url):
    migrations.upgrade(url)
    from alembic import command

    command.downgrade(migrations.alembic_config(url), "base")
    assert _tables(url) == {"alembic_version"}
    migrations.upgrade(url, migrations.INITIAL)
    assert "next_scan_after" not in {c["name"] for c in asyncio.run(
        _run(url, lambda conn: inspect(conn).get_columns("offers")))}
    migrations.upgrade(url)
    assert _diff(url) == []


def test_adopts_create_all_database(url, monkeypatch, capsys):
    asyncio.run(create_all(make_engine(url)))
    monkeypatch.setenv("DEALRADAR_DATABASE_URL", url)
    assert cli.main(["init-db"]) == 0  # old command name still works
    assert f"adopted pre-migration database at revision {migrations.PRODUCT_CATEGORY}" in capsys.readouterr().out
    assert _version(url) == migrations.PRODUCT_CATEGORY and _diff(url) == []


def test_adopts_create_all_database_without_backoff_column(url):
    # databases created before the scan dispatcher's failure backoff (offers.next_scan_after) existed
    asyncio.run(create_all(make_engine(url)))
    asyncio.run(_run(url, _drop_category))
    asyncio.run(_run(url, lambda conn: conn.execute(text("ALTER TABLE offers DROP COLUMN next_scan_after"))))
    assert migrations.upgrade(url) == migrations.INITIAL
    assert _version(url) == migrations.PRODUCT_CATEGORY and _diff(url) == []


def test_adopts_database_without_category_and_backfills_it(url):
    # databases created before products.category existed: stamped at 0002, then 0003 classifies existing rows
    asyncio.run(create_all(make_engine(url)))

    def seed(conn):
        _drop_category(conn)
        conn.execute(text("INSERT INTO products (id, brand, model, name, created_at, updated_at) VALUES "
                          "('00000000000000000000000000000001', 'Apple', '', 'Apple iPhone 16 128GB', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    asyncio.run(_run(url, seed))
    assert migrations.upgrade(url) == migrations.OFFER_BACKOFF
    assert _version(url) == migrations.PRODUCT_CATEGORY and _diff(url) == []
    assert asyncio.run(_run(url, lambda conn: conn.execute(text("SELECT category FROM products")).scalar())) == "phones"
