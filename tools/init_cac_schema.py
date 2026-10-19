"""Initialize only an empty, dedicated CAC PostgreSQL database.

Unlike db.init_db(), this command never runs schema.sql's DROP statements.
The source SQLite volume remains attached as a separate backup.
"""

import os
import re
from pathlib import Path

from infra.cac_isolation import validate


def main():
    if os.environ.get("CAC_ISOLATED_DEPLOYMENT") != "true":
        raise RuntimeError("CAC schema initialization requires CAC_ISOLATED_DEPLOYMENT=true")
    validate()

    import db

    if not db.using_postgres():
        raise RuntimeError("CAC schema initialization requires PostgreSQL")
    conn = db.connect()
    try:
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        ).fetchall()
        names = {row["table_name"] for row in tables}
        if names:
            if {"users", "designs", "teams", "schema_migrations",
                "pending_model_uploads"}.issubset(names):
                print("CAC schema already initialized; no DDL executed")
                return
            raise RuntimeError("CAC database contains an incomplete or foreign schema; refusing initialization")

        schema = (Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")
        schema = re.sub(r"^DROP TABLE IF EXISTS [^;]+;\s*", "", schema, flags=re.M | re.I)
        if re.search(r"^\s*(DROP|TRUNCATE|DELETE)\s", schema, flags=re.M | re.I):
            raise RuntimeError("CAC schema includes destructive SQL; refusing initialization")
        conn.executescript(schema)
        print("CAC schema initialized on empty PostgreSQL database")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
