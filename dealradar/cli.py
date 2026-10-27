"""Operator commands. `make-admin user@example.com` grants admin rights (never grantable via the API);
`migrate` brings the database to the current schema with the Alembic migrations (`init-db` is the old name).
Databases created by the old create_all-based init-db are adopted automatically."""
import argparse
import asyncio
import sys

from sqlalchemy import select

from dealradar.core.config import get_settings
from dealradar.core.db import make_engine, make_session_factory
from dealradar.models import User


async def set_admin(session_factory, email: str, admin: bool = True) -> bool:
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()
        if user is None:
            return False
        user.is_admin = admin
        await session.commit()
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dealradar.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", aliases=["init-db"])
    for name in ("make-admin", "revoke-admin"):
        sub.add_parser(name).add_argument("email")
    args = parser.parse_args(argv)
    if args.command in ("migrate", "init-db"):
        from dealradar import migrations

        legacy = migrations.upgrade(get_settings().database_url)
        if legacy:
            print(f"adopted pre-migration database at revision {legacy}")
        print("database at latest migration")
        return 0
    factory = make_session_factory(make_engine(get_settings().database_url))
    ok = asyncio.run(set_admin(factory, args.email, args.command == "make-admin"))
    print(f"{args.command}: {args.email}" if ok else f"no such user: {args.email}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
