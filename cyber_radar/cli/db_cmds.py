"""`cyber-radar db init` - reproducible database initialization.

Applies db/schema.sql (CREATE TABLE IF NOT EXISTS throughout - safe to
run against an already-initialized database, a no-op for existing
tables). Requires DATABASE_URL to point at a database the connecting
role can create tables in - this command does not create the database
or role itself (see docs/INSTALLATION.md for that one-time step, which
needs a superuser and is intentionally not automated).
"""
from __future__ import annotations

import argparse
import os
import sys


def _schema_path() -> str:
    # cyber_radar/cli/db_cmds.py -> repo root -> db/schema.sql
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "db", "schema.sql")


def cmd_init(_args: argparse.Namespace) -> int:
    from .. import config

    path = _schema_path()
    if not os.path.isfile(path):
        print(f"Schema file not found: {path}", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as f:
        schema_sql = f.read()

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed - run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
            conn.execute(schema_sql)
    except Exception as e:  # noqa: BLE001
        print(f"Schema initialization failed: {type(e).__name__}: {e}", file=sys.stderr)
        print("Common cause: the database/role in DATABASE_URL doesn't exist yet, or lacks CREATE privileges - see docs/INSTALLATION.md.", file=sys.stderr)
        return 1

    print("Database schema initialized (or already up to date).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyber-radar db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create/update the database schema").set_defaults(func=cmd_init)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
