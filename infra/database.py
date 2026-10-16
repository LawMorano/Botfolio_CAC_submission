"""Postgres support, for when the database moves to RDS or Railway.

The application is ~2,200 lines of hand-written SQLite SQL. Rewriting every
query for Postgres would be a large change to working code and a large number
of chances to break something, so this module does the opposite: it makes
Postgres accept the SQL that is already there.

Two mechanisms, in order of how much work they do:

  1. **Compatibility functions installed in the database.** SQLite's
     `datetime('now', '-15 minutes')` appears 53 times across app.py and
     schema.sql. Rather than rewriting each one, `install_compat()` creates a
     Postgres function called `datetime` with matching behaviour. Every one of
     those call sites then works unchanged — including the two that pass the
     modifier as a bound parameter, which a regex could not have handled.

  2. **A small statement translator** for the handful of things a function
     cannot cover: parameter style (`?` to `%s`), `INSERT OR IGNORE`, and
     SQLite's case-insensitive `LIKE`.

The connection object mimics `sqlite3.Connection` closely enough that db.py can
return either one and nothing upstream can tell the difference.

STATUS: exercised by tools/check_postgres.py, which runs the real schema and a
representative query from every route against a live Postgres. Run it before
pointing production at RDS — a translation layer is only as good as the
statements it has actually seen.
"""

import logging
import re
import threading

from infra.settings import settings

log = logging.getLogger("botfolio")

_compat_installed = set()
_id_tables_cache = {}
_cache_lock = threading.Lock()

# Serializes compatibility DDL across Gunicorn worker processes. A Python
# threading lock cannot protect separate processes, while a Postgres advisory
# transaction lock can. The arbitrary, stable integer only namespaces this
# application's startup lock inside the database.
_COMPAT_ADVISORY_LOCK = 20260812


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

class Row:
    """A row that behaves like `sqlite3.Row`, because app.py assumes one.

    Three access styles are all used in the existing code and all have to keep
    working:

        row["title"]                     templates, everywhere
        row[0]                           app.py:589
        dict(cursor.fetchall())          app.py:353, two-column rows to a dict

    The last one is why `__iter__` yields values rather than keys: `dict()` on
    a list of rows unpacks each row as a (key, value) pair.
    """

    __slots__ = ("_keys", "_values")

    def __init__(self, keys, values):
        self._keys = keys
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._keys.index(key)]
            except ValueError:
                raise KeyError(key)
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, key):
        return key in self._keys

    def keys(self):
        """Present so that `dict(row)` uses the mapping protocol."""
        return list(self._keys)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __repr__(self):
        return f"<Row {dict(zip(self._keys, self._values))!r}>"


# --------------------------------------------------------------------------
# Statement translation
# --------------------------------------------------------------------------

_INSERT_TABLE = re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+([a-zA-Z_][\w]*)", re.I)


def _convert_placeholders(sql):
    """Turn SQLite's `?` into psycopg's `%s`, ignoring quoted text.

    A blind replace would corrupt any `?` inside a string literal, and would
    also leave real `%` characters unescaped — psycopg treats `%` as the start
    of a placeholder, so a literal one has to be doubled.
    """
    out = []
    quote = None
    for char in sql:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "?":
            out.append("%s")
        elif char == "%":
            out.append("%%")
        else:
            out.append(char)
    return "".join(out)


_IS_DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I)


def translate(sql):
    """Rewrite one SQLite statement for Postgres.

    Kept deliberately small. Everything that can be handled by a compatibility
    function in the database is handled there instead, because a function is
    exact and a regex over SQL is a guess.
    """
    # ensure_runtime_schema() creates tables at start-up, not just seed.py, and
    # eight of them declare INTEGER PRIMARY KEY AUTOINCREMENT. Without this the
    # app would fail on its first migration against Postgres. Scoped to DDL so
    # that a column or value in an ordinary query can never be rewritten.
    if _IS_DDL.match(sql):
        sql = translate_schema(sql)

    # SQLite overloads IS as a null-safe equality test, so `season_id IS ?`
    # matches when both sides are NULL. Postgres reserves IS for IS NULL /
    # IS TRUE and rejects a parameter after it; IS NOT DISTINCT FROM is the
    # equivalent. app.py:1449 relies on this to find season-less archetypes.
    sql = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", sql, flags=re.I)
    # `INSERT OR IGNORE INTO x ...` -> `INSERT INTO x ... ON CONFLICT DO NOTHING`.
    # The clause goes at the end, which is valid for both the VALUES and the
    # INSERT...SELECT forms used in consolidate_tags().
    ignored = False
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", sql, re.I):
        sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", sql, flags=re.I)
        ignored = True

    # SQLite's LIKE is case-insensitive for ASCII; Postgres's is not. Search
    # would quietly stop matching "Slides" for "slides" without this.
    sql = re.sub(r"\bLIKE\b", "ILIKE", sql, flags=re.I)
    # ILIKE already ignores case, so the collation hint is now redundant — and
    # NOCASE does not exist in Postgres.
    sql = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.I)

    if ignored:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    return _convert_placeholders(sql)


def translate_schema(sql):
    """Rewrite schema.sql's DDL. Used by seed.py when pointed at Postgres."""
    # Identity columns. `INTEGER PRIMARY KEY AUTOINCREMENT` is SQLite's
    # rowid alias; `GENERATED BY DEFAULT` (rather than ALWAYS) is used so that
    # an explicit id can still be supplied when importing existing data.
    sql = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        sql, flags=re.I,
    )
    # Case-insensitive uniqueness on username/email is expressed as COLLATE
    # NOCASE in SQLite. Dropping it here would let two accounts differ only by
    # capitalisation, so the lost constraint is re-added as a functional unique
    # index in install_compat().
    sql = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.I)
    sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
    # SQLite accepts these silently; Postgres does not have them.
    sql = re.sub(r"\bWITHOUT\s+ROWID\b", "", sql, flags=re.I)
    # schema.sql opens with `PRAGMA foreign_keys = ON;`. Postgres enforces
    # foreign keys unconditionally, so the statement is not just unsupported —
    # it is unnecessary. Dropped rather than translated.
    sql = re.sub(r"^\s*PRAGMA\b[^;]*;", "", sql, flags=re.I | re.M)
    return sql


# --------------------------------------------------------------------------
# Compatibility functions installed into Postgres
# --------------------------------------------------------------------------

# Timestamps are stored as TEXT in this schema ('2026-08-04 12:00:00'), written
# and compared as strings throughout. Keeping that representation — rather than
# converting the schema to `timestamptz` and rewriting every comparison — is
# what lets the existing queries run untouched.
_COMPAT_SQL = """
CREATE OR REPLACE FUNCTION datetime(ts text) RETURNS text AS $$
  SELECT to_char(
    CASE WHEN lower(btrim($1)) = 'now'
         THEN (now() AT TIME ZONE 'UTC')
         ELSE $1::timestamp END,
    'YYYY-MM-DD HH24:MI:SS');
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION datetime(ts text, modifier text) RETURNS text AS $$
  -- SQLite modifiers used by this app are all of the form '-15 minutes' or
  -- '+30 minutes', which Postgres parses directly as an interval.
  SELECT to_char(
    (CASE WHEN lower(btrim($1)) = 'now'
          THEN (now() AT TIME ZONE 'UTC')
          ELSE $1::timestamp END) + $2::interval,
    'YYYY-MM-DD HH24:MI:SS');
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION julianday(ts text) RETURNS double precision AS $$
  SELECT EXTRACT(EPOCH FROM (
    CASE WHEN lower(btrim($1)) = 'now'
         THEN (now() AT TIME ZONE 'UTC')
         ELSE $1::timestamp END)) / 86400.0 + 2440587.5;
$$ LANGUAGE sql IMMUTABLE;
"""

# COLLATE NOCASE is dropped during schema translation, which would otherwise
# allow "Rahul" and "rahul" to register as two accounts. These restore it.
_CASE_INSENSITIVE_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_ci ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_ci    ON users (lower(email));
"""


def install_compat(raw_connection, with_indexes=True):
    """Create compatibility objects in one serialized transaction.

    Gunicorn workers start concurrently, so releasing the advisory lock
    between the function and index DDL lets their PostgreSQL catalog locks
    interleave and deadlock.  Keep one transaction-level lock until all DDL
    for this pass has either completed or been skipped.
    """
    cursor = raw_connection.cursor()
    try:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (_COMPAT_ADVISORY_LOCK,),
        )
        cursor.execute(_COMPAT_SQL)
        if with_indexes:
            # This runs before seed.py creates tables on a fresh database.
            # Check first instead of deliberately failing index DDL, because
            # an error would abort the transaction containing the functions.
            cursor.execute("SELECT to_regclass('users')")
            if cursor.fetchone()[0] is not None:
                cursor.execute(_CASE_INSENSITIVE_INDEXES)
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.close()


# --------------------------------------------------------------------------
# Connection wrapper
# --------------------------------------------------------------------------

class Cursor:
    """Wraps a psycopg cursor to look like the sqlite3 one app.py expects."""

    def __init__(self, raw, lastrowid=None):
        self._raw = raw
        self.lastrowid = lastrowid

    def _rows(self, records):
        if not self._raw.description:
            return []
        keys = [column[0] for column in self._raw.description]
        return [Row(keys, tuple(record)) for record in records]

    def fetchone(self):
        if not self._raw.description:
            return None
        record = self._raw.fetchone()
        return self._rows([record])[0] if record is not None else None

    def fetchall(self):
        if not self._raw.description:
            return []
        return self._rows(self._raw.fetchall())

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._raw.rowcount


class Connection:
    """A `sqlite3.Connection` work-alike backed by Postgres."""

    def __init__(self, dsn):
        self._raw = _connect_raw(dsn)
        self._dsn = dsn
        if dsn not in _compat_installed:
            install_compat(self._raw)
            _compat_installed.add(dsn)

    # -- the sqlite3 surface app.py uses --------------------------------

    def execute(self, sql, params=()):
        statement = translate(sql)

        # PRAGMAs have no Postgres equivalent and are intercepted rather than
        # sent. `PRAGMA table_info` in particular drives ensure_runtime_schema's
        # "has this column been added yet" check, so it has to return rows in
        # the same shape.
        pragma = _pragma(statement)
        if pragma is not None:
            return self._pragma(pragma)

        cursor = self._raw.cursor()
        # `lastrowid` after an INSERT is used 7 times in app.py (to link a new
        # design to its images, and so on). Postgres has no equivalent, so a
        # RETURNING clause is added to inserts on tables that have an id.
        wants_id = self._insert_returns_id(statement)
        if wants_id:
            statement = statement.rstrip().rstrip(";") + " RETURNING id"

        try:
            cursor.execute(statement, tuple(params))
        except Exception:
            # Postgres aborts the entire transaction on the first error, and
            # db.get_db() caches one connection in g.db for the whole request --
            # including the render of error.html. Without this rollback every
            # later statement raises InFailedSqlTransaction, so the error page
            # dies too and the browser shows a bare "HTTP ERROR 500" instead.
            # Anything uncommitted is already lost to the abort; rolling back
            # only makes the connection usable again.
            try:
                self._raw.rollback()
            except Exception:
                pass
            raise

        lastrowid = None
        if wants_id:
            record = cursor.fetchone()
            # None when ON CONFLICT DO NOTHING suppressed the insert.
            lastrowid = record[0] if record else None
            # The RETURNING result has been consumed; hide the description so
            # a later fetchall() on this cursor cannot return a stray id row.
            cursor = _Consumed(cursor)

        return Cursor(cursor, lastrowid)

    def executescript(self, script):
        """Run schema.sql. Statement-splitting is left to the server."""
        cursor = self._raw.cursor()
        cursor.execute(translate_schema(script))
        self._raw.commit()
        cursor.close()
        install_compat(self._raw)
        return Cursor(cursor)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    # -- internals -------------------------------------------------------

    def _insert_returns_id(self, statement):
        """Whether this INSERT targets a table with a generated `id`.

        Junction tables (design_tags, team_members, tag_votes) have composite
        primary keys and no id column, and asking for `RETURNING id` there is a
        hard error — so the target table is checked rather than assumed.
        """
        if "RETURNING" in statement.upper():
            return False
        match = _INSERT_TABLE.match(statement)
        if not match:
            return False
        return match.group(1).lower() in self._id_tables()

    def _id_tables(self):
        """Tables owning an `id` column, read once per process."""
        with _cache_lock:
            cached = _id_tables_cache.get(self._dsn)
        if cached is not None:
            return cached

        cursor = self._raw.cursor()
        cursor.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND column_name = 'id'"
        )
        tables = {row[0].lower() for row in cursor.fetchall()}
        cursor.close()
        with _cache_lock:
            _id_tables_cache[self._dsn] = tables
        return tables

    def _pragma(self, pragma):
        name, argument = pragma
        if name == "table_info":
            cursor = self._raw.cursor()
            # ensure_runtime_schema() reads row["name"] from this, so the
            # column is aliased to match SQLite's output.
            cursor.execute(
                "SELECT column_name AS name, data_type AS type "
                "FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s",
                (argument,),
            )
            return Cursor(cursor)
        # `PRAGMA foreign_keys = ON` is SQLite catching up to what Postgres
        # does by default. Nothing to do.
        return Cursor(_Empty())


def _pragma(statement):
    match = re.match(r"^\s*PRAGMA\s+(\w+)\s*(?:\(\s*([\w]+)\s*\))?", statement, re.I)
    if not match:
        return None
    return match.group(1).lower(), match.group(2)


class _Empty:
    """A cursor that yields nothing, for intercepted statements."""
    description = None
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Consumed:
    """Hides a cursor whose only result row was the RETURNING id."""

    description = None

    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def _connect_raw(dsn):
    """Open a driver connection, preferring psycopg3 and accepting psycopg2."""
    # RDS requires TLS on new instances and Railway supports it; asking for it
    # explicitly means a misconfigured URL fails loudly instead of sending the
    # database password across the network in the clear.
    if "sslmode=" not in dsn and not settings.is_local:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"

    try:
        import psycopg

        return psycopg.connect(dsn, autocommit=False)
    except ImportError:
        pass

    import psycopg2

    return psycopg2.connect(dsn)


def connect(dsn=None):
    return Connection(dsn or settings.database_url)
