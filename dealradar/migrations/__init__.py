"""Alembic schema migrations. `python -m dealradar.cli migrate` (or `alembic upgrade head`) brings a database to
the current schema. Databases made by the old `create_all`-based init-db are adopted (stamped) first."""
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from dealradar.core.db import make_engine

INITIAL = "0001_initial"
OFFER_BACKOFF = "0002_offer_next_scan_after"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent))
    cfg.attributes["url"] = url  # passed out of band: '%' in passwords would break ini interpolation
    return cfg


def _legacy_revision(sync_conn) -> str | None:
    """Revision matching a pre-Alembic database (tables made by create_all), or None if it isn't one."""
    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    if "alembic_version" in tables or "offers" not in tables:
        return None
    columns = {c["name"] for c in insp.get_columns("offers")}
    return OFFER_BACKOFF if "next_scan_after" in columns else INITIAL


async def _detect_legacy(url: str) -> str | None:
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_legacy_revision)
    finally:
        await engine.dispose()


def upgrade(url: str, revision: str = "head") -> str | None:
    """Migrate the database at `url`; returns the revision a legacy database was stamped at, if any."""
    legacy = asyncio.run(_detect_legacy(url))
    cfg = alembic_config(url)
    if legacy:
        command.stamp(cfg, legacy)
    command.upgrade(cfg, revision)
    return legacy
