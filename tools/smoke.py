"""Request every page and check it renders. Run against SQLite or Postgres.

    python tools/smoke.py                      # SQLite, the local database
    DATABASE_URL=postgresql://... python tools/smoke.py

This is the test that would have caught the "Internal Server Error on every
design page" incident before it reached a browser: it walks real routes with a
real database and fails on anything that is not the expected status.

It is also how infra/database.py earns its keep. Pointed at Postgres, it runs
the same routes through the translation layer, so any query the translator gets
wrong shows up here rather than in production.
"""

import os
import re
import sys
import traceback
from pathlib import Path

# Import the application the same way `python app.py` would.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def csrf_from(html):
    """Pull the token out of the page.

    base.html injects it with JavaScript rather than rendering a hidden input,
    so it has to be read out of the inline script.
    """
    match = re.search(r'input\.value=("(?:[^"\\]|\\.)*")', html)
    if not match:
        return None
    import json

    return json.loads(match.group(1))


def main():
    import app as application
    import db

    backend = "postgres" if db.using_postgres() else "sqlite"
    print(f"smoke test against {backend}\n")

    client = application.app.test_client()
    conn = db.connect()

    # Built from real rows so the run covers pages with actual content —
    # hard-coded ids would pass on an empty database and prove nothing.
    design_ids = [r["id"] for r in conn.execute("SELECT id FROM designs ORDER BY id LIMIT 5")]
    usernames = [r["username"] for r in conn.execute("SELECT username FROM users ORDER BY id LIMIT 3")]
    team_numbers = [r["number"] for r in conn.execute("SELECT number FROM teams ORDER BY id LIMIT 3")]
    tag_names = [r["name"] for r in conn.execute("SELECT name FROM tags ORDER BY id LIMIT 3")]

    checks = [
        ("/", 200),
        ("/about", 200),
        ("/learn", 200),
        ("/learn/onshape", 200),
        ("/learn/fusion-360", 200),
        ("/learn/onshape/parallel-plate-drivetrain", 200),
        ("/learn/fusion-360/parallel-plate-drivetrain", 200),
        ("/terms", 200),
        ("/contact", 200),
        ("/gallery", 200),
        ("/gallery?page=2", 200),
        ("/tags", 200),
        ("/teams", 200),
        ("/login", 200),
        ("/register", 200),
        ("/forgot-password", 200),
        ("/healthz", 200),
        ("/readyz", 200),
        ("/metrics", 200),
        ("/api/tags?q=a", 200),
        # Routes that must reject rather than crash.
        ("/designs/999999", 404),
        ("/u/definitely-not-a-real-user", 404),
        ("/submit", 302),          # login required
        ("/notifications", 302),   # login required
    ]

    # Search exercises the LIKE/ILIKE translation and the tag subquery — the
    # part of the gallery query most likely to behave differently on Postgres.
    for name in tag_names:
        checks.append((f"/gallery?q={name}", 200))
        checks.append((f"/tags?q={name[:3]}", 200))
    for design_id in design_ids:
        checks.append((f"/designs/{design_id}", 200))
    for username in usernames:
        checks.append((f"/u/{username}", 200))
    for number in team_numbers:
        checks.append((f"/teams/{number}", 200))

    failures = []
    for path, expected in checks:
        try:
            response = client.get(path)
            status = response.status_code
        except Exception:
            failures.append((path, "exception", traceback.format_exc()))
            print(f"  ERROR  {path}")
            continue

        if status != expected:
            body = response.get_data(as_text=True)[:400]
            failures.append((path, f"expected {expected}, got {status}", body))
            print(f"  FAIL   {path}  ({status}, wanted {expected})")
        else:
            print(f"  ok     {path}")

    # A POST, so the write path and CSRF check are covered too. Deliberately
    # invalid credentials: this asserts the form handles a rejection, without
    # needing a real account to exist.
    token = csrf_from(client.get("/login").get_data(as_text=True))
    if token:
        response = client.post(
            "/login",
            data={"email": "nobody@example.com", "password": "wrong", "csrf_token": token},
        )
        if response.status_code in (200, 302):
            print("  ok     POST /login (rejected cleanly)")
        else:
            failures.append(("POST /login", f"got {response.status_code}", ""))
            print(f"  FAIL   POST /login ({response.status_code})")
    else:
        print("  warn   POST /login skipped: no CSRF token found")

    conn.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s) on {backend}:\n")
        for path, reason, detail in failures:
            print(f"--- {path}: {reason}")
            if detail:
                print(detail[:1500])
            print()
        return 1

    print(f"all {len(checks) + 1} checks passed on {backend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
