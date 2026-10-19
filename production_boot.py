"""Prepare a Railway volume and start Gunicorn without resetting existing data."""

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent


def _link_empty_image_directory(source, target):
    """Replace only an image directory shipped empty by the Docker image."""
    if source.is_symlink():
        if source.resolve() != target.resolve():
            raise RuntimeError(f"Unexpected storage link: {source}")
        return
    if source.exists():
        entries = list(source.iterdir())
        if any(entry.name != ".gitkeep" or not entry.is_file() for entry in entries):
            raise RuntimeError(f"Refusing to replace a nonempty storage directory: {source}")
        for entry in entries:
            entry.unlink()
        source.rmdir()
    source.symlink_to(target, target_is_directory=True)


def prepare_volume(data_dir, app_root=APP_ROOT):
    """Link persistent uploads and initialize the schema on first boot only."""
    data_dir = Path(data_dir)
    app_root = Path(app_root)
    if not data_dir.is_absolute() or not data_dir.is_dir() or data_dir.is_symlink():
        raise RuntimeError("BOTFOLIO_DATA_DIR must be an existing absolute volume mount")
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("BOTFOLIO_DATA_DIR cannot be combined with DATABASE_URL")

    for name in ("uploads", "models"):
        target = data_dir / name
        target.mkdir(exist_ok=True)
        _link_empty_image_directory(app_root / "static" / name, target)

    database = data_dir / "designhub.db"
    if not database.exists():
        # init_db is destructive when run against an existing file. This check
        # ensures a restart or deploy can never invoke it on production data.
        import db

        if db.DB_PATH.resolve() != database.resolve():
            raise RuntimeError("Database path is not on the mounted volume")
        db.init_db()
    else:
        import db

        if not db.db_is_initialized():
            raise RuntimeError("Existing volume database has no Botfolio schema")


def _own_volume(data_dir, uid, gid):
    for root, dirs, files in os.walk(data_dir, followlinks=False):
        os.chown(root, uid, gid)
        for name in dirs + files:
            path = Path(root) / name
            if not path.is_symlink():
                os.chown(path, uid, gid)


def main():
    from infra.cac_isolation import validate

    validate()
    if os.environ.get("CAC_ISOLATED_DEPLOYMENT") == "true":
        from tools.init_cac_schema import main as init_cac_schema

        init_cac_schema()
    data_dir = os.environ.get("BOTFOLIO_DATA_DIR")
    if data_dir:
        import pwd

        if os.geteuid() != 0:
            raise RuntimeError("Volume setup requires RAILWAY_RUN_UID=0")
        mount_path = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        if mount_path and Path(mount_path).resolve() != Path(data_dir).resolve():
            raise RuntimeError("BOTFOLIO_DATA_DIR differs from the Railway volume mount")
        prepare_volume(data_dir)
        # Run schema migrations once before Gunicorn forks its workers. Each
        # worker also checks migrations, but this avoids concurrent first boot
        # DDL against one SQLite file.
        import app  # noqa: F401

        account = pwd.getpwnam("botfolio")
        _own_volume(data_dir, account.pw_uid, account.pw_gid)
        os.environ["HOME"] = account.pw_dir
        os.environ["USER"] = account.pw_name
        os.environ["LOGNAME"] = account.pw_name
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)

    port = os.environ.get("PORT", "8080")
    os.execvp("gunicorn", [
        "gunicorn", "--bind", f"0.0.0.0:{port}", "--workers", "2",
        "--threads", "4", "--timeout", "300", "--graceful-timeout", "30",
        "--access-logfile", "-", "--error-logfile", "-", "app:app",
    ])


if __name__ == "__main__":
    main()
