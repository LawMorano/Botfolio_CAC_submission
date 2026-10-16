"""Database connection handling for Botfolio.

By default this is a single SQLite file (`designhub.db`) sitting next to this
module. It is gitignored; run `python seed.py` to build it from `schema.sql`.

Setting DATABASE_URL switches every connection to Postgres instead — for RDS,
or Railway's Postgres plugin — without changing any query in the application.
The translation that makes that work lives in infra/database.py; this module
only decides which of the two to open.

Callers do not need to know which is in use. Both return an object with the
same `execute`/`fetchone`/`fetchall`/`commit` surface and rows that can be
read as `row["title"]`.
"""

import importlib
import logging
import os
import sqlite3
from pathlib import Path

from flask import g

from infra.settings import settings

# A UNIQUE violation arrives as a different exception class per driver, and
# app.py has to be able to catch one without knowing which backend is open.
INTEGRITY_ERRORS = (sqlite3.IntegrityError,)
for _driver in ("psycopg", "psycopg2"):
    try:
        INTEGRITY_ERRORS += (importlib.import_module(_driver).IntegrityError,)
    except Exception:
        pass  # Not installed here, so nothing in this process can raise it.

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("BOTFOLIO_DATA_DIR") or BASE_DIR) / "designhub.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def using_postgres():
    return settings.uses_postgres


def connect():
    """Open a connection with the settings this app expects everywhere."""
    if using_postgres():
        from infra import database

        return database.connect()

    conn = sqlite3.connect(DB_PATH)
    # Rows behave like dicts, so templates can do `design["title"]`.
    conn.row_factory = sqlite3.Row
    # SQLite ships with foreign keys OFF by default. Our ON DELETE CASCADE
    # rules (votes dying with their design, etc.) do nothing without this.
    conn.execute("PRAGMA foreign_keys = ON")
    # Readers no longer block on a writer, which is what produces "database is
    # locked" when someone uploads while someone else is browsing. Harmless on
    # a laptop, and the difference between working and not if SQLite is kept on
    # a mounted volume in production instead of moving to Postgres.
    conn.execute("PRAGMA journal_mode = WAL")
    # Wait for a lock rather than failing instantly on contention.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db():
    """Per-request connection, reused within a single request."""
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exception=None):
    """Registered as a teardown handler in app.py."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """(Re)create every table from schema.sql. Destroys existing data."""
    conn = connect()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def db_exists():
    if using_postgres():
        # There is no file to look for; reachability is the equivalent question.
        try:
            conn = connect()
            conn.close()
            return True
        except Exception:
            return False
    return DB_PATH.exists()


def db_is_initialized():
    """Return whether the database contains the application's core schema."""
    if using_postgres():
        try:
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = 'users'"
                ).fetchone()
                return row is not None
            finally:
                conn.close()
        except Exception:
            # Unreachable is not the same as uninitialised, but both mean "do
            # not try to run migrations against it yet". Log it: silence here
            # means a worker boots with every migration skipped and no other
            # sign of it, so any table or column the migration would have added
            # is simply absent for the life of that worker.
            logging.getLogger(__name__).exception(
                "could not check whether the database is initialised; "
                "skipping runtime migrations for this worker"
            )
            return False

    if not db_exists():
        return False
    conn = connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        return row is not None
    finally:
        conn.close()
