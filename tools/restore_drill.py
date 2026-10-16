"""Run a non-destructive PostgreSQL backup/restore drill against a scratch database.

DATABASE_URL is the source. RESTORE_TEST_DATABASE_URL must identify a separate,
disposable database. The script refuses matching URLs, creates a custom-format
backup, restores it with --clean, and verifies core row counts before recording
a successful drill in docs/restore-drills/. It never marks a drill successful
unless pg_dump, pg_restore, and verification all complete.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
RECORD_DIR = ROOT / "docs" / "restore-drills"
TABLES = ("users", "designs", "design_images", "comments", "content_reports")


def redacted(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def run(command):
    subprocess.run(command, check=True)


def counts(url):
    query = " UNION ALL ".join(
        f"SELECT '{table}',COUNT(*) FROM {table}" for table in TABLES
    )
    result = subprocess.run(
        ["psql", url, "-At", "-F", "=", "-c", query],
        check=True, capture_output=True, text=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def main():
    source = (os.environ.get("DATABASE_URL") or "").strip()
    target = (os.environ.get("RESTORE_TEST_DATABASE_URL") or "").strip()
    if not source or not target:
        raise SystemExit("Set DATABASE_URL and RESTORE_TEST_DATABASE_URL.")
    if source == target or redacted(source) == redacted(target):
        raise SystemExit("The restore target must be a separate disposable database.")
    for binary in ("pg_dump", "pg_restore", "psql"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} is required on PATH.")

    with tempfile.TemporaryDirectory(prefix="botfolio-restore-") as temp:
        backup = Path(temp) / "botfolio.dump"
        run(["pg_dump", "--format=custom", "--no-owner", "--file", str(backup), source])
        before = counts(source)
        run(["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", target, str(backup)])
        after = counts(target)
        if before != after:
            raise SystemExit(f"Restore verification failed: source={before}, restored={after}")

    timestamp = datetime.now(timezone.utc)
    RECORD_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "performed_at": timestamp.isoformat(), "successful": True,
        "source": redacted(source), "target": redacted(target), "verified_counts": after,
    }
    path = RECORD_DIR / f"{timestamp:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Restore drill succeeded. Record: {path}")


if __name__ == "__main__":
    main()
