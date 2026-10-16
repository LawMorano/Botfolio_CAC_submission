"""Parse every SQL statement in the codebase as Postgres, after translation.

    python tools/check_translation.py

infra/database.py claims it can run this application's SQLite SQL on Postgres.
This checks that claim against every statement that actually exists, rather
than against the handful someone thought to try.

How it works: walk the source with `ast` and collect every string that looks
like SQL, translate it, then hand the result to pglast — the real PostgreSQL
grammar, as a library. Anything the server would reject fails here.

What this does *not* prove is semantics. A statement can parse perfectly and
still return the wrong rows, so tools/smoke.py exercises real routes against a
live Postgres in CI. This catches the syntax class of bug in a second, without
a database; that one catches the rest.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from infra.database import translate, translate_schema  # noqa: E402

SQL_START = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|WITH)\b", re.I
)


def looks_like_sql(text):
    """A leading keyword is not enough on its own.

    app.py:255 lists the HTTP methods that need a CSRF token, and one of them
    is the bare string "DELETE". Requiring a second token keeps words that
    merely happen to be SQL keywords out of the check.
    """
    return bool(SQL_START.match(text)) and len(text.split()) > 1


def sql_strings(path):
    """Every complete SQL string constant in a Python file, with line numbers.

    Returns (static, dynamic). Statements assembled with an f-string go in the
    second list: what the interpolated part contains is only known at run time,
    so they cannot be parsed here and are reported for tools/smoke.py to cover
    against a live database instead. Pretending to check them — by substituting
    a stand-in for the expression — produces failures about the stand-in rather
    than about the SQL, which is worse than not checking them.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    # Constants that are *parts* of an f-string are visited twice by ast.walk:
    # once inside the JoinedStr and once on their own. On their own they are
    # fragments like "ALTER TABLE " that could never parse. Collect their ids
    # so they can be skipped.
    inside_fstring = set()
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                inside_fstring.add(id(part))
        # A module, class or function docstring is a bare string expression.
        # seed.py's begins with the word "Create", which SQL_START matches.
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))

    static, dynamic = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                part.value for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if looks_like_sql(literal):
                dynamic.append((node.lineno, literal))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in inside_fstring or id(node) in docstrings:
                continue
            if looks_like_sql(node.value):
                static.append((node.lineno, node.value))

    return static, dynamic


def parseable(statement):
    """Hand a translated statement to the PostgreSQL parser."""
    import pglast

    # psycopg's placeholders are not SQL. Swap them for Postgres's own numbered
    # parameters, which the grammar does accept, and undo the %% escaping.
    prepared = statement.replace("%s", "$1").replace("%%", "%")
    pglast.parse_sql(prepared)


def check(label, statements, translator):
    failures = []
    skipped = 0

    for lineno, raw in statements:
        # PRAGMAs never reach Postgres — Connection.execute intercepts them and
        # answers from information_schema instead. See _pragma().
        if raw.strip().upper().startswith("PRAGMA"):
            skipped += 1
            continue

        translated = translator(raw)
        try:
            parseable(translated)
        except Exception as exc:
            failures.append((lineno, raw.strip()[:160], translated.strip()[:200], str(exc)[:200]))

    checked = len(statements) - skipped
    status = "FAIL" if failures else "ok"
    print(f"  {status:<5} {label}: {checked} statements parsed, {skipped} intercepted")
    return failures


def main():
    print("translating every SQL statement and parsing it as Postgres\n")

    all_failures = []
    all_dynamic = []

    for name in ("app.py", "seed.py", "maintenance.py"):
        path = ROOT / name
        if not path.exists():
            continue
        static, dynamic = sql_strings(path)
        all_failures += check(name, static, translate)
        all_dynamic += [(name, lineno, text) for lineno, text in dynamic]

    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    try:
        import pglast

        pglast.parse_sql(translate_schema(schema))
        print("  ok    schema.sql: full DDL parsed")
    except Exception as exc:
        print("  FAIL  schema.sql")
        all_failures.append((0, "schema.sql", "", str(exc)[:300]))

    # The compatibility functions are what let datetime('now', '-1 day') work
    # unchanged, so they have to be valid too.
    from infra.database import _COMPAT_SQL

    try:
        import pglast

        pglast.parse_sql(_COMPAT_SQL)
        print("  ok    compatibility functions parsed")
    except Exception as exc:
        print("  FAIL  compatibility functions")
        all_failures.append((0, "_COMPAT_SQL", "", str(exc)[:300]))

    if all_dynamic:
        # Named rather than silently skipped: these are exactly the statements
        # most likely to hide a dialect problem, so it should be obvious that
        # the live run in CI is the only thing covering them.
        print(f"\n  {len(all_dynamic)} statement(s) built with f-strings — "
              "not statically checkable, covered by tools/smoke.py:")
        for name, lineno, text in all_dynamic:
            print(f"         {name}:{lineno}  {' '.join(text.split())[:80]}…")

    print()
    if all_failures:
        print(f"{len(all_failures)} statement(s) would not parse:\n")
        for lineno, original, translated, error in all_failures:
            print(f"--- line {lineno}")
            print(f"    original:   {original}")
            print(f"    translated: {translated}")
            print(f"    error:      {error}\n")
        return 1

    print("every statement translates to valid Postgres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
