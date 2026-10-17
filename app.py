"""Botfolio's Flask application and HTTP routes."""

import base64
import binascii
import io
import json
import logging
import math
import os
import posixpath
import re
import secrets
import hashlib
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse
from functools import wraps
from pathlib import Path


def eastern_time(moment):
    """Convert UTC to US Eastern time without requiring an OS tzdata bundle."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    utc = moment.astimezone(timezone.utc)
    year = utc.year
    march_1 = datetime(year, 3, 1, tzinfo=timezone.utc)
    first_sunday_march = 1 + ((6 - march_1.weekday()) % 7)
    dst_start = datetime(year, 3, first_sunday_march + 7, 7, tzinfo=timezone.utc)
    november_1 = datetime(year, 11, 1, tzinfo=timezone.utc)
    first_sunday_november = 1 + ((6 - november_1.weekday()) % 7)
    dst_end = datetime(year, 11, first_sunday_november, 6, tzinfo=timezone.utc)
    offset = -4 if dst_start <= utc < dst_end else -5
    return utc.astimezone(timezone(timedelta(hours=offset)))

from dotenv import load_dotenv

# Local secrets use .env.local; non-secret defaults may remain in .env.
load_dotenv(".env.local")
load_dotenv()

from services.openai_service import (is_configured as openai_is_configured,
                                     moderate_public_content, review_design)
from services.openai_service import ModerationRejected, MODEL as OPENAI_MODEL
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import db
from services import email_service, team_service
from robotics import frc_teams, ftc_teams
import infra
from infra import cache, ratelimit
from infra import storage as infra_storage
from infra.settings import settings
from config import (ADMIN_EMAIL, ADMIN_USERNAME, COPYRIGHT_EMAIL,
                    DAILY_DOWNLOAD_LIMIT, DOWNLOAD_COOLDOWN_MINUTES, LEGAL_EMAIL,
                    LEGAL_CHANGE_SUMMARY, LEGAL_NOTICE_VERSION,
                    MAX_TAGS_PER_DESIGN, MAX_TAG_LENGTH, NEW_TAG_LIMIT_PER_HOUR,
                    PRIVACY_EMAIL, PRIVACY_VERSION, SECURITY_EMAIL, SUPPORT_EMAIL,
                    TAG_LOW_SCORE,
                    TERMS_VERSION, UPLOAD_CERTIFICATION_VERSION,
                    UPLOAD_LIMIT_10_MINUTES, UPLOAD_LIMIT_DAILY,
                    VIEW_COUNT_START_LABEL, VISIT_COOLDOWN_MINUTES)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
MODEL_DIR = BASE_DIR / "static" / "models"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# STL/OBJ are single-mesh parts. GLB carries a whole assembly — the part
# hierarchy plus any baked motion (mates exported as animation) — in one
# self-contained binary, which the viewer can play and take apart interactively.
VIEWABLE_MODEL_EXTENSIONS = {".stl", ".obj", ".glb"}
# STEP is what teams hand each other in CAD: solids that reopen as editable
# geometry rather than the frozen triangles a mesh export leaves behind. It is
# a boundary representation, and turning one into triangles needs an
# OpenCascade kernel the browser does not carry, so a STEP file is stored,
# listed, and downloaded like any other model while its preview comes from the
# uploaded picture instead of the viewer.
CAD_SOURCE_EXTENSIONS = {".step", ".stp"}
MODEL_EXTENSIONS = VIEWABLE_MODEL_EXTENSIONS | CAD_SOURCE_EXTENSIONS
# The same allowlist in the phrasing the error messages use.
MODEL_FORMATS_PHRASE = "STL, OBJ, GLB, or STEP"
FTC_ROLES = {
    "student": "Student",
    "mentor": "Mentor",
    "coach": "Coach",
    "affiliate": "Robotics affiliate",
}
TEAM_PROGRAMS = {"ftc": "FTC", "frc": "FRC"}

ROBOTICS_INTERESTS = [
    "CAD", "Mechanical", "Programming", "Autonomous", "Vision", "Electrical",
    "Fabrication", "Strategy", "Scouting", "Drive Team", "Outreach", "Mentor", "Other",
]
ONBOARDING_INTERESTS = [
    "CAD & Mechanical", "Programming", "Autonomous & Vision", "Electrical",
    "Fabrication", "Strategy & Scouting", "Drive Team", "Outreach", "Mentoring",
    "Just exploring",
]
CONTRIBUTOR_ROLES = [
    "CAD", "Mechanical", "Programming", "Electrical", "Fabrication", "Testing",
    "Controls", "Other",
]
# "Download only" is the absence of a CAD platform rather than one more entry in
# the list: the file itself is the whole offer, so there is no document to link
# out to and no Open-CAD button on the design page.
CAD_DOWNLOAD_ONLY = "download-only"
CAD_SOFTWARE = {
    "onshape": "Onshape", "fusion-360": "Fusion 360",
    "solidworks": "SolidWorks", "inventor": "Autodesk Inventor",
    "freecad": "FreeCAD", "creo": "PTC Creo", "other": "Other CAD",
    CAD_DOWNLOAD_ONLY: "Download only",
}
# A quick-share design is a link and nothing else, so the one choice that means
# "there is no link" would leave it with nothing to open or download.
LINKED_CAD_SOFTWARE = {key: label for key, label in CAD_SOFTWARE.items()
                       if key != CAD_DOWNLOAD_ONLY}
FOUNDING_TEAM_LIMIT = 50
FOUNDING_CONTRIBUTOR_LIMIT = 100

SITE_SEARCH_PAGES = [
    ("CAD Academy", "learn", "learn courses onshape fusion 360 ftc drivetrain cad academy"),
    ("Gallery", "gallery", "designs cad robots mechanisms browse"),
    ("Teams", "team_list", "robotics teams directory"),
    ("Founding 50", "founding_50", "founding teams first 50 history"),
    ("Tags", "tag_directory", "tags topics mechanisms categories"),
    ("About Botfolio", "about", "about educational robotics community ai feedback"),
    ("Submit a design", "submit", "upload publish share design cad"),
    ("Account settings", "account_settings", "account email password profile settings"),
    ("Community Rules", "community_rules", "community rules moderation conduct"),
    ("Help", "help", "help how it works getting started guide contact support email"),
    ("Contact", "contact", "contact support help"),
]

# Reference choices belong to the application, not only to seed.py. Production
# databases are often created without demo data, so these are inserted
# idempotently during startup and never replace community-created rows.
from robotics.catalog import SEASONS as DEFAULT_SEASONS

# Stable, cross-season taxonomy. Season-specific vocabulary remains available
# as tags/archetypes for backwards compatibility.
DESIGN_TYPES = {
    "full-robot": "Full Robot", "robot-subsystem": "Robot Subsystem",
    "component-part": "Component / Part", "tool-fixture": "Tool / Fixture",
    "field-practice": "Field / Practice Element", "other": "Other",
}
DESIGN_FUNCTIONS = {
    "drivetrain": "Drivetrain / Mobility", "intake": "Intake / Acquisition",
    "transfer": "Transfer / Storage", "scoring": "Scoring / Manipulation",
    "arm-lift": "Arm / Lift / Turret", "endgame": "Endgame / Climbing",
    "structure": "Structure", "controls": "Electronics / Controls",
}
DEFAULT_ARCHETYPES = {
    "frc-rebuilt-2026": [
        ("Full Robot", "full-robot"),
        ("Intake", "intake"),
        ("Scoring Mechanism", "scoring-mechanism"),
        ("Climber", "climber"),
        ("Drivetrain", "drivetrain"),
    ],
    "frc-reefscape-2025": [
        ("Full Robot", "full-robot"),
        ("Coral Intake", "coral-intake"),
        ("Coral Scorer", "coral-scorer"),
        ("Algae Mechanism", "algae-mechanism"),
        ("Barge Climber", "barge-climber"),
    ],
    "frc-crescendo-2024": [
        ("Full Robot", "full-robot"),
        ("Note Intake", "note-intake"),
        ("Shooter", "shooter"),
        ("Climber", "climber"),
    ],
    "frc-charged-up-2023": [
        ("Full Robot", "full-robot"),
        ("Game Piece Intake", "game-piece-intake"),
        ("Grid Scorer", "grid-scorer"),
        ("Charge Station Mechanism", "charge-station-mechanism"),
    ],
    "decode": [
        ("Full Robot", "full-robot"),
        ("Artifact Intake", "artifact-intake"),
        ("Artifact Transfer", "artifact-transfer"),
        ("Artifact Storage", "artifact-storage"),
        ("Turreted Shooter", "turreted-shooter"),
        ("Fixed Shooter", "fixed-shooter"),
    ],
    "into-the-deep": [
        ("Specimen Intake", "specimen-intake"),
        ("Sample Intake", "sample-intake"),
        ("Specimen Scorer", "specimen-scorer"),
        ("Sample Scorer", "sample-scorer"),
        ("Ascent Mechanism", "ascent-mechanism"),
    ],
    "centerstage": [
        ("Pixel Intake", "pixel-intake"),
        ("Backdrop Scorer", "backdrop-scorer"),
        ("Drone Launcher", "drone-launcher"),
        ("Hanging Mechanism", "hanging-mechanism"),
    ],
    "powerplay": [
        ("Cone Intake", "cone-intake"),
        ("Junction Scorer", "junction-scorer"),
        ("Cone Transfer", "cone-transfer"),
    ],
}

MAX_IMAGE_BYTES = 8 * 1024 * 1024     # per-image limit, enforced in the view
#was 32MG now 100MG
MAX_INLINE_MODEL_BYTES = 350_000_000
AUTO_VIEW_MODEL_BYTES = 350_000_000
MAX_VIEW_MODEL_BYTES = 500_000_000
MAX_MODEL_BYTES = 2_500_000_000
MODEL_UPLOAD_PART_BYTES = 64 * 1024 * 1024
MAX_IMAGE_EDGE = 1600                 # downscale anything larger

# A hard ceiling on how many pixels an uploaded image may decode to, regardless
# of how few bytes it takes on disk. A "decompression bomb" is a tiny file — a
# solid-colour 20000x20000 PNG is well under the 8 MB byte cap — that balloons
# into gigabytes of raw pixels the moment Pillow opens it, which is an easy way
# to exhaust a worker's memory. Pillow's own guard only *raises* above 2x this
# value; between 1x and 2x it merely warns and decodes anyway, so
# sanitize_image_bytes enforces the exact ceiling itself from the image header
# before allocating any pixels.
MAX_IMAGE_PIXELS = 50_000_000         # 50 MP — far above any real photo/screenshot
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# The sitemap protocol caps a single file at 50,000 URLs. SITEMAP_MAX bounds
# each individual section's query (designs, teams, contributors) so no one of
# them can scan an unbounded table on a public route — the teams table in
# particular grows a stub row per credited team number and trends into the tens
# of thousands. SITEMAP_URL_LIMIT is the hard cap on the combined total, so the
# three sections plus the static pages can never push a single file past the
# protocol limit no matter how the data grows.
SITEMAP_MAX = 20_000
SITEMAP_URL_LIMIT = 45_000

# Statuses that mean this request handed the design over. 200 is a completed
# local send, 302 is the redirect to a signed storage URL or out to the CAD host,
# and 206 answers a Range request — which on local disk returns the entire file
# to anything that sends "Range: bytes=0-", so it is a whole download whatever
# the status line calls it. Counting 206 does not double-count resumed transfers:
# the one-row-per-person-per-design check in record_design_download already
# collapses those. Left out are 304, which sends no bytes because the browser
# already has them, and 4xx/5xx, which serve nothing at all.
DOWNLOAD_COUNTED_STATUSES = {200, 206, 302}

# A tag at or below this score is treated as wrong: hidden on the design page
# and excluded from search matching.
BURIED_SCORE = -2

# The shelf order the gallery and the homepage grid list designs in, ahead of
# whatever sort the visitor asked for. Three keys, applied in turn:
#
#   1. Quick shares last. A link-only share is a pointer to someone else's CAD
#      host rather than a design published here, so it sits behind everything
#      no matter who posted it. It is recognised the same way the quick edit
#      form recognises one: no prototype version and no model file.
#   2. Teams, then individuals, then admins. Work by a real team leads, an
#      individual builder's follows, and anything Botfolio itself published
#      comes last -- the admin flag is checked first because an admin upload
#      credited to a team is still Botfolio's upload, which is exactly how the
#      design card labels it.
#   3. Full robots before single mechanisms, by archetype. Written as EXISTS so
#      it needs no join and drops into any query that has `designs d` in scope.
#
# Portable across SQLite and Postgres: plain CASE expressions and a COALESCE
# rather than anything either dialect spells its own way.
DESIGN_SHELF_ORDER = """
        CASE WHEN d.prototype_version IS NULL
              AND COALESCE(d.model_filename, '') = '' THEN 1 ELSE 0 END,
        CASE WHEN d.uploaded_by_admin = 1 THEN 2
             WHEN d.team_id IS NOT NULL THEN 0
             ELSE 1 END,
        CASE WHEN EXISTS (SELECT 1 FROM archetypes ar
                           WHERE ar.id = d.archetype_id AND ar.slug = 'full-robot')
             THEN 0 ELSE 1 END"""

app = Flask(__name__)

# A random per-run key is fine for local development — it just means sessions
# don't survive a restart. In a hosted environment it is a bug: every process
# would sign cookies with a different key, so sessions break across restarts and
# across replicas (a login on one container is rejected by the next). Require a
# real key anywhere that isn't local, and fail fast at boot rather than serving
# with a silently broken login. Set FLASK_SECRET_KEY in .env for a stable one.
_secret_key = os.environ.get("FLASK_SECRET_KEY")
if not _secret_key:
    if not settings.is_local:
        raise RuntimeError(
            "FLASK_SECRET_KEY must be set outside local development — without a "
            "stable key, sessions break across restarts and replicas."
        )
    _secret_key = secrets.token_hex(32)
app.config["SECRET_KEY"] = _secret_key

# Flask has a single global request-size cap, so it has to accommodate the
# largest thing we accept (a model file). Tighter per-field limits are applied
# by hand in the upload helpers below.
app.config["MAX_CONTENT_LENGTH"] = 400 * 1024 * 1024
app.teardown_appcontext(db.close_db)

# Tell the storage layer where the local folders are before anything can try to
# write to them, then attach logging, security headers, metrics, limits and
# caching. With no environment variables set this changes nothing about how the
# app behaves locally — see infra/__init__.py.
infra_storage.configure(UPLOAD_DIR, MODEL_DIR)
infra.install(app)


_RUNTIME_SCHEMA_ADVISORY_LOCK = 7_218_044_632


def _ensure_bigint_byte_counters(conn):
    """Let storage accounting safely exceed PostgreSQL's 2 GB INTEGER cap."""
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=5"
    ).fetchone() is not None:
        return

    if db.using_postgres():
        for table, column in (
            ("users", "storage_limit_bytes"),
            ("users", "storage_used_bytes"),
            ("designs", "model_size_bytes"),
            ("designs", "storage_bytes"),
            ("pending_model_uploads", "declared_size_bytes"),
        ):
            conn.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT"
            )

    # Failed publishes can leave the cached counter stale. Published design
    # rows are authoritative, so repair every account as part of the upgrade.
    conn.execute(
        """UPDATE users SET storage_used_bytes=COALESCE((
               SELECT SUM(storage_bytes) FROM designs
               WHERE designs.user_id=users.id
                 AND designs.upload_status NOT IN ('rejected','removed')
           ),0)"""
    )
    conn.execute("INSERT INTO schema_migrations(version) VALUES (5)")


def _backfill_founding_badges(conn):
    """Align launch badges with the published-design eligibility rules."""
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=6"
    ).fetchone() is not None:
        return

    # A Founding Contributor must personally upload an approved design. Rank
    # the first 100 uploaders by their first qualifying design, not by account
    # creation time or by being credited on somebody else's upload.
    conn.execute(
        "UPDATE users SET founding_contributor_rank=NULL,founding_contributor_at=NULL"
    )
    uploaders = conn.execute(
        """SELECT user_id,MIN(created_at) qualified_at FROM designs
             WHERE is_hidden=0 AND upload_status='approved'
             GROUP BY user_id ORDER BY qualified_at,user_id LIMIT ?""",
        (FOUNDING_CONTRIBUTOR_LIMIT,),
    ).fetchall()
    for rank, row in enumerate(uploaders, 1):
        conn.execute(
            "UPDATE users SET founding_contributor_rank=?,founding_contributor_at=? WHERE id=?",
            (rank, row["qualified_at"], row["user_id"]),
        )

    # Preserve permanent team ranks, then fill any remaining Founding 50 spots
    # for registered, named teams that already have an approved team design.
    claimed = conn.execute(
        "SELECT COUNT(*) n FROM teams WHERE founding_rank IS NOT NULL"
    ).fetchone()["n"]
    remaining = max(0, FOUNDING_TEAM_LIMIT - claimed)
    if remaining:
        teams = conn.execute(
            """SELECT t.id,MIN(d.created_at) qualified_at
                 FROM teams t JOIN designs d ON d.team_id=t.id
                WHERE t.founding_rank IS NULL AND t.profile_status='claimed'
                  AND trim(t.name)!=''
                  AND d.is_hidden=0 AND d.upload_status='approved'
                  AND (d.team_attribution_accepted=1 OR EXISTS (
                       SELECT 1 FROM memberships m
                        WHERE m.team_id=t.id AND m.user_id=d.user_id))
                GROUP BY t.id ORDER BY qualified_at,t.id LIMIT ?""",
            (remaining,),
        ).fetchall()
        for rank, row in enumerate(teams, claimed + 1):
            conn.execute(
                "UPDATE teams SET is_founding=1,founding_rank=?,founding_qualified_at=? WHERE id=?",
                (rank, row["qualified_at"], row["id"]),
            )

    conn.execute("INSERT INTO schema_migrations(version) VALUES (6)")


def _migrate_team_references(conn):
    """Separate admin credits from team-owned Botfolio profiles."""
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=7"
    ).fetchone() is not None:
        return

    # An empty team created solely so an admin could give credit is a reference,
    # not a claim by that team. Admin attributions require later confirmation.
    conn.execute(
        """UPDATE teams SET profile_status='reference',is_founding=0,
                  founding_rank=NULL,founding_qualified_at=NULL
             WHERE owner_id IS NULL
               AND NOT EXISTS (SELECT 1 FROM memberships m WHERE m.team_id=teams.id)
               AND EXISTS (SELECT 1 FROM designs d WHERE d.team_id=teams.id
                            AND d.uploaded_by_admin=1)"""
    )
    conn.execute(
        "UPDATE designs SET team_attribution_accepted=0 "
        "WHERE uploaded_by_admin=1 AND team_id IS NOT NULL"
    )
    conn.execute(
        """UPDATE teams SET is_founding=0,founding_rank=NULL,
                  founding_qualified_at=NULL
             WHERE founding_rank IS NOT NULL AND NOT EXISTS (
                   SELECT 1 FROM designs d
                    WHERE d.team_id=teams.id AND d.is_hidden=0
                      AND d.upload_status='approved'
                      AND (d.team_attribution_accepted=1 OR EXISTS (
                           SELECT 1 FROM memberships m
                            WHERE m.team_id=teams.id AND m.user_id=d.user_id)))"""
    )
    # False awards may leave holes. Preserve the relative order of every valid
    # founder while compacting ranks so the next award remains within 1..50.
    founders = conn.execute(
        "SELECT id FROM teams WHERE founding_rank IS NOT NULL ORDER BY founding_rank,id"
    ).fetchall()
    conn.execute(
        "UPDATE teams SET founding_rank=-founding_rank WHERE founding_rank IS NOT NULL"
    )
    for rank, founder in enumerate(founders, 1):
        conn.execute(
            "UPDATE teams SET founding_rank=? WHERE id=?", (rank, founder["id"])
        )
    conn.execute("INSERT INTO schema_migrations(version) VALUES (7)")


def _ensure_program_schema(conn):
    """Move the original FTC-only tables to program-aware identities.

    Team numbers overlap between FTC and FRC, so adding a column is not enough:
    the old unique constraint on ``number`` has to become a composite one. The
    SQLite table rebuild is deliberately kept here instead of scattered through
    request handlers, which makes old installs upgrade once and stay boring.
    """
    team_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(teams)").fetchall()
    }
    if "program" not in team_columns:
        if db.using_postgres():
            conn.execute("ALTER TABLE teams ADD COLUMN program TEXT NOT NULL DEFAULT 'ftc'")
            conn.execute("ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_number_key")
        else:
            # PRAGMA foreign_keys cannot change inside a transaction.
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            fields = {
                "biography": "''", "profile_image": "NULL", "banner_image": "NULL",
                "website_url": "NULL", "social_links": "'{}'", "other_links": "'{}'",
                "is_founding": "0", "founding_rank": "NULL",
                "founding_qualified_at": "NULL", "profile_status": "'claimed'",
            }
            selected = {
                name: name if name in team_columns else fallback
                for name, fallback in fields.items()
            }
            conn.executescript(
                f"""
                CREATE TABLE teams_program_aware (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    program TEXT NOT NULL DEFAULT 'ftc',
                    number INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    region TEXT NOT NULL DEFAULT '',
                    biography TEXT NOT NULL DEFAULT '',
                    profile_image TEXT,
                    banner_image TEXT,
                    website_url TEXT,
                    social_links TEXT NOT NULL DEFAULT '{{}}',
                    other_links TEXT NOT NULL DEFAULT '{{}}',
                    is_founding INTEGER NOT NULL DEFAULT 0 CHECK (is_founding IN (0,1)),
                    founding_rank INTEGER UNIQUE,
                    founding_qualified_at TEXT,
                    profile_status TEXT NOT NULL DEFAULT 'claimed'
                        CHECK (profile_status IN ('reference','claimed')),
                    owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    invite_code TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(program, number)
                );
                INSERT INTO teams_program_aware(
                    id,program,number,name,region,biography,profile_image,banner_image,
                    website_url,social_links,other_links,is_founding,founding_rank,
                    founding_qualified_at,profile_status,owner_id,invite_code,created_at)
                SELECT id,'ftc',number,name,region,{selected['biography']},
                       {selected['profile_image']},{selected['banner_image']},
                       {selected['website_url']},{selected['social_links']},
                       {selected['other_links']},{selected['is_founding']},
                       {selected['founding_rank']},{selected['founding_qualified_at']},
                       {selected['profile_status']},owner_id,invite_code,created_at
                  FROM teams;
                DROP TABLE teams;
                ALTER TABLE teams_program_aware RENAME TO teams;
                """
            )
            conn.execute("PRAGMA foreign_keys=ON")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_program_number "
        "ON teams(program,number)"
    )

    for table in ("seasons", "designs"):
        columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if "program" not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN program TEXT NOT NULL DEFAULT 'ftc'"
            )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_program ON designs(program)")


def _ensure_runtime_schema(conn):
    """Apply additive runtime schema changes using an existing connection."""
    _ensure_program_schema(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at    TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reset_user ON password_reset_tokens(user_id)"
    )
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_email_verification_user ON email_verification_tokens(user_id);
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            ip_address TEXT,
            details TEXT NOT NULL DEFAULT '{}',
            occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_security_events_occurred ON security_events(occurred_at);
        CREATE INDEX IF NOT EXISTS idx_security_events_user ON security_events(user_id,occurred_at);
        CREATE TABLE IF NOT EXISTS retention_holds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            released_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_retention_holds_target ON retention_holds(target_type,target_id,released_at,expires_at);
        CREATE TABLE IF NOT EXISTS user_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);
    """)

    columns = {
    row["name"]
    for row in conn.execute("PRAGMA table_info(designs)").fetchall()
    }

    if "onshape_link" not in columns:
        conn.execute("ALTER TABLE designs ADD COLUMN onshape_link TEXT")

    if "cad_software" not in columns:
        conn.execute("ALTER TABLE designs ADD COLUMN cad_software TEXT")
    if "cad_link" not in columns:
        conn.execute("ALTER TABLE designs ADD COLUMN cad_link TEXT")
    conn.execute("UPDATE designs SET cad_software='onshape', cad_link=onshape_link "
                 "WHERE onshape_link IS NOT NULL AND onshape_link != '' AND cad_software IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_designs_cad_software ON designs(cad_software)")

    for name, definition in (("prototype_version", "INTEGER"),
                             ("competition_tested", "INTEGER NOT NULL DEFAULT 0"),
                             ("length_in", "REAL"), ("width_in", "REAL"),
                             ("height_in", "REAL"),
                             ("dimension_unit", "TEXT NOT NULL DEFAULT 'in'"),
                             ("motor_count", "INTEGER"),
                             ("servo_count", "INTEGER")):
        if name not in columns:
            conn.execute(f"ALTER TABLE designs ADD COLUMN {name} {definition}")

    # Additive upgrades preserve all existing accounts and content.
    upgrades = {
        "users": [("is_admin", "INTEGER NOT NULL DEFAULT 0"),
                  ("display_name", "TEXT NOT NULL DEFAULT ''"),
                  ("location", "TEXT NOT NULL DEFAULT ''"),
                  ("contact_email", "TEXT NOT NULL DEFAULT ''"),
                  ("website_url", "TEXT"),
                  ("social_links", "TEXT NOT NULL DEFAULT '{}'"),
                  ("profile_image", "TEXT"),
                  ("tagline", "TEXT NOT NULL DEFAULT ''"),
                  ("specialties", "TEXT NOT NULL DEFAULT ''"),
                  ("cad_tools", "TEXT NOT NULL DEFAULT ''"),
                  ("ftc_role", "TEXT"),
                  ("interests", "TEXT NOT NULL DEFAULT ''"),
                  ("ftc_team_number", "INTEGER"),
                  ("founding_contributor_rank", "INTEGER"),
                  ("founding_contributor_at", "TEXT"),
                  ("onboarding_complete", "INTEGER NOT NULL DEFAULT 1"),
                  ("accepted_terms_version", "TEXT"),
                  ("accepted_terms_at", "TEXT"),
                  ("accepted_privacy_version", "TEXT"),
                  ("accepted_privacy_at", "TEXT"),
                  ("acknowledged_legal_version", "TEXT"),
                  ("acknowledged_legal_at", "TEXT"),
                  ("age_13_confirmed", "INTEGER NOT NULL DEFAULT 0"),
                  ("minor_permission_confirmed", "INTEGER NOT NULL DEFAULT 0"),
                  ("registration_ip", "TEXT"),
                  ("email_verified_at", "TEXT"),
                  # See schema.sql: how that date came to be set, recorded at
                  # the moment it is written instead of inferred later.
                  ("email_verified_source", "TEXT"),
                  ("suspended_at", "TEXT"),
                  ("suspended_until", "TEXT"),
                  ("banned_at", "TEXT"),
                  ("deleted_at", "TEXT"),
                  ("storage_limit_bytes", "BIGINT NOT NULL DEFAULT 1073741824"),
                  ("storage_used_bytes", "BIGINT NOT NULL DEFAULT 0"),
                  # Google's stable account id, and which credential the row
                  # was born with. The uniqueness lives in an index created
                  # after this loop -- SQLite cannot add a UNIQUE column with
                  # ALTER TABLE, and a unique index treats NULLs as distinct on
                  # both backends, so every password-only row coexists.
                  ("google_sub", "TEXT"),
                  ("auth_provider", "TEXT NOT NULL DEFAULT 'password'")],
        "designs": [("upload_certification_version", "TEXT"),
                    ("upload_certification_accepted", "INTEGER NOT NULL DEFAULT 0"),
                    ("uploaded_by_admin", "INTEGER NOT NULL DEFAULT 0"),
                    ("is_hidden", "INTEGER NOT NULL DEFAULT 0"),
                    ("model_size_bytes", "BIGINT NOT NULL DEFAULT 0"),
                    ("model_sha256", "TEXT"),
                    ("storage_bytes", "BIGINT NOT NULL DEFAULT 0"),
                    ("upload_status", "TEXT NOT NULL DEFAULT 'approved'"),
                    ("team_attribution_accepted", "INTEGER NOT NULL DEFAULT 1"),
                    ("design_type", "TEXT NOT NULL DEFAULT 'other'"),
                    ("replacement_cost_low_cents", "INTEGER"),
                    ("replacement_cost_high_cents", "INTEGER"),
                    ("replacement_cost_currency", "TEXT NOT NULL DEFAULT 'USD'")],
        "design_of_week_awards": [("current_week", "TEXT")],
        "teams": [("biography", "TEXT NOT NULL DEFAULT ''"), ("profile_image", "TEXT"),
                  ("banner_image", "TEXT"), ("website_url", "TEXT"),
                  ("social_links", "TEXT NOT NULL DEFAULT '{}'"),
                  ("other_links", "TEXT NOT NULL DEFAULT '{}'"),
                  ("is_founding", "INTEGER NOT NULL DEFAULT 0"),
                  ("founding_rank", "INTEGER"),
                  ("founding_qualified_at", "TEXT"),
                  ("profile_status", "TEXT NOT NULL DEFAULT 'claimed'")],
        "design_tags": [("low_score_since", "TEXT")],
        "tags": [("key", "TEXT NOT NULL DEFAULT ''")],
        "pending_model_uploads": [("multipart_upload_id", "TEXT"),
                                  ("upload_completed_at", "TEXT"),
                                  ("promoted_at", "TEXT")],
        "content_reports": [("workflow_status", "TEXT NOT NULL DEFAULT 'new'"),
                            ("assigned_admin_id", "INTEGER"),
                            ("decision_reason", "TEXT NOT NULL DEFAULT ''"),
                            ("priority", "INTEGER NOT NULL DEFAULT 1"),
                            ("action_taken_at", "TEXT")],
    }
    for table, additions in upgrades.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in additions:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    # After the loop: it names a column that loop is what creates.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)")
    conn.execute(
        "UPDATE content_reports SET priority=3,urgent=1 "
        "WHERE reason IN ('threat','youth_safety','intimate','privacy_danger','malware')"
    )
    conn.execute(
        "UPDATE content_reports SET priority=2 "
        "WHERE reason IN ('confidential','harassment','impersonation','copyright','spam','manipulation')"
    )
    # This stamps a verification date onto rows nobody ever verified, so it
    # says so in the row. Sign in with Google reads that flag before it will
    # link a Google account to a Botfolio one on the strength of a matching
    # address -- see routes/google_signin._has_real_inbox_proof.
    conn.execute("UPDATE users SET email_verified_at=created_at,email_verified_source='backfill' WHERE email_verified_at IS NULL AND accepted_terms_version IS NULL")
    # One-time capture for rows an earlier boot backfilled before the column
    # existed. Their fingerprint is the date copied verbatim from created_at;
    # every genuine writer of email_verified_at now names itself, so an
    # unnamed source can only be a pre-existing genuine verification.
    conn.execute("UPDATE users SET email_verified_source='backfill' WHERE email_verified_source IS NULL AND email_verified_at IS NOT NULL AND email_verified_at=created_at")
    conn.execute("UPDATE users SET accepted_privacy_at=accepted_terms_at WHERE accepted_privacy_at IS NULL AND accepted_privacy_version IS NOT NULL")
    consolidate_tags(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS design_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, visitor_key TEXT NOT NULL, visited_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_design_visits ON design_visits(design_id, visitor_key, visited_at);
        CREATE TABLE IF NOT EXISTS design_view_events (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, viewed_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_design_view_events_design ON design_view_events(design_id, viewed_at);
        CREATE TABLE IF NOT EXISTS design_view_state (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, visitor_key TEXT NOT NULL, last_viewed_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (design_id, visitor_key));
        CREATE TABLE IF NOT EXISTS design_downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, visitor_key TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'file', downloaded_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS design_likes (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, design_id));
        CREATE INDEX IF NOT EXISTS idx_design_likes_design ON design_likes(design_id);
        CREATE TABLE IF NOT EXISTS saved_designs (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (user_id, design_id));
        CREATE INDEX IF NOT EXISTS idx_saved_designs_user ON saved_designs(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS design_contributors (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT, credited_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (design_id, user_id));
        CREATE INDEX IF NOT EXISTS idx_design_contributors_user ON design_contributors(user_id, credited_at DESC);
        CREATE TABLE IF NOT EXISTS comment_helpful (comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (comment_id, user_id));
        CREATE INDEX IF NOT EXISTS idx_comment_helpful_comment ON comment_helpful(comment_id);
        CREATE TABLE IF NOT EXISTS design_of_week_awards (design_id INTEGER PRIMARY KEY REFERENCES designs(id) ON DELETE CASCADE, selected_by INTEGER REFERENCES users(id) ON DELETE SET NULL, selected_at TEXT NOT NULL DEFAULT (datetime('now')), is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)));
        CREATE TABLE IF NOT EXISTS design_of_week_history (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, week_start TEXT NOT NULL, selected_by INTEGER REFERENCES users(id) ON DELETE SET NULL, selected_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY(design_id,week_start));
        CREATE INDEX IF NOT EXISTS idx_design_of_week_history_week ON design_of_week_history(week_start,selected_at DESC);
        CREATE TABLE IF NOT EXISTS upload_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_upload_attempts ON upload_attempts(user_id, created_at);
        CREATE TABLE IF NOT EXISTS pending_model_uploads (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE, original_filename TEXT NOT NULL, object_filename TEXT NOT NULL UNIQUE, declared_size_bytes BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','rejected')), expires_at TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')), consumed_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_pending_model_uploads_user ON pending_model_uploads(user_id,status,expires_at);
        CREATE TABLE IF NOT EXISTS featured_designs (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 6), PRIMARY KEY(user_id,design_id), UNIQUE(user_id,position));
        CREATE TABLE IF NOT EXISTS design_images (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, filename TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(design_id,position));
        CREATE INDEX IF NOT EXISTS idx_design_images_design ON design_images(design_id,position);
        CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE, body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 2000), status TEXT NOT NULL DEFAULT 'visible' CHECK(status IN ('visible','hidden','deleted')), created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_comments_design ON comments(design_id,created_at,id);
        CREATE INDEX IF NOT EXISTS idx_comments_user ON comments(user_id,created_at DESC);
        CREATE TABLE IF NOT EXISTS comment_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE, reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')), created_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_at TEXT, UNIQUE(comment_id,reporter_id));
        CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL, design_id INTEGER REFERENCES designs(id) ON DELETE CASCADE, comment_id INTEGER REFERENCES comments(id) ON DELETE CASCADE, kind TEXT NOT NULL CHECK(kind IN ('comment','reply')), read_at TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,read_at,created_at DESC);
        CREATE TABLE IF NOT EXISTS team_membership_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, initiated_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL CHECK(kind IN ('invitation','request')), status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','denied','cancelled')), created_at TEXT NOT NULL DEFAULT (datetime('now')), responded_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_team_membership_requests_user ON team_membership_requests(user_id,status,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_team_membership_requests_team ON team_membership_requests(team_id,status,created_at DESC);
        CREATE TABLE IF NOT EXISTS content_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL, content_type TEXT NOT NULL, content_id TEXT, content_url TEXT NOT NULL, reason TEXT NOT NULL, description TEXT NOT NULL, reporter_email TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved','dismissed')), urgent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_content_reports_status ON content_reports(status,urgent,created_at);
        CREATE INDEX IF NOT EXISTS idx_content_reports_workflow ON content_reports(workflow_status,urgent,created_at);
        CREATE TABLE IF NOT EXISTS moderation_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, target_type TEXT NOT NULL, target_id TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS security_incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_number TEXT NOT NULL UNIQUE, discovery_date TEXT NOT NULL, discovered_by TEXT NOT NULL, systems_affected TEXT NOT NULL, information_affected TEXT NOT NULL, actions_taken TEXT NOT NULL, credentials_rotated TEXT NOT NULL, vendors_contacted TEXT NOT NULL, notifications TEXT NOT NULL, root_cause TEXT NOT NULL, corrective_action TEXT NOT NULL, resolution_date TEXT, created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT, created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_security_incidents_dates ON security_incidents(resolution_date,discovery_date DESC);

        -- Indexes covering the joins that had none. design_tags is keyed on
        -- (design_id, tag_id), which serves "tags on this design" from the
        -- primary key but leaves "designs with this tag" — the gallery's tag
        -- search, and the count on every row of the tag directory — scanning
        -- the whole table. Same for the vote sums, which are grouped by tag.
        CREATE INDEX IF NOT EXISTS idx_design_tags_tag ON design_tags(tag_id);
        CREATE INDEX IF NOT EXISTS idx_tag_votes_tag ON tag_votes(tag_id);
        -- The download count on each design card.
        CREATE INDEX IF NOT EXISTS idx_design_downloads_design ON design_downloads(design_id);
        CREATE TABLE IF NOT EXISTS design_functions (design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, function_key TEXT NOT NULL, PRIMARY KEY(design_id,function_key));
        CREATE INDEX IF NOT EXISTS idx_design_functions_key ON design_functions(function_key,design_id);
        CREATE TABLE IF NOT EXISTS design_resources (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, kind TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', function_key TEXT, filename TEXT, original_filename TEXT, size_bytes BIGINT NOT NULL DEFAULT 0, sha256 TEXT, position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_design_resources_design ON design_resources(design_id,position,id);
        CREATE TABLE IF NOT EXISTS resource_downloads (id INTEGER PRIMARY KEY AUTOINCREMENT, resource_id INTEGER NOT NULL REFERENCES design_resources(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL, visitor_key TEXT NOT NULL, downloaded_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_resource_downloads_resource ON resource_downloads(resource_id,downloaded_at);
        CREATE TABLE IF NOT EXISTS design_relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, source_design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, target_design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, relationship_type TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id) ON DELETE SET NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(source_design_id,target_design_id,relationship_type));
        CREATE INDEX IF NOT EXISTS idx_design_relationships_source ON design_relationships(source_design_id,relationship_type);
        CREATE TABLE IF NOT EXISTS bom_items (id INTEGER PRIMARY KEY AUTOINCREMENT, design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE, part_name TEXT NOT NULL, part_number TEXT NOT NULL DEFAULT '', manufacturer TEXT NOT NULL DEFAULT '', quantity REAL NOT NULL DEFAULT 1, unit TEXT NOT NULL DEFAULT 'ea', unit_cost_cents INTEGER, product_url TEXT, notes TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_bom_items_design ON bom_items(design_id,position,id);

    """)
    # Downloads used to be counted per request, so a deployed database holds
    # rows with no record of who made them. Those keep an empty key, which no
    # live visitor can ever match — their counts stand, and the first real
    # download after this deploys is still counted rather than deduplicated
    # against a stranger's row.
    download_columns = {row["name"] for row in conn.execute("PRAGMA table_info(design_downloads)")}
    if "visitor_key" not in download_columns:
        conn.execute("ALTER TABLE design_downloads ADD COLUMN visitor_key TEXT NOT NULL DEFAULT ''")
    # Every row that predates the CAD-link button is a stored-file download, so
    # 'file' is the right value to backfill and the right default to keep.
    if "kind" not in download_columns:
        conn.execute("ALTER TABLE design_downloads ADD COLUMN kind TEXT NOT NULL DEFAULT 'file'")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_downloads_visitor "
        "ON design_downloads(design_id, visitor_key, downloaded_at)"
    )
    # The daily budget asks what one person has taken lately across every
    # design, which the index above cannot answer: it leads with design_id.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_downloads_budget "
        "ON design_downloads(visitor_key, downloaded_at)"
    )
    conn.execute("""INSERT OR IGNORE INTO design_images(design_id,filename,position)
                    SELECT id,image_filename,0 FROM designs
                    WHERE image_filename IS NOT NULL AND image_filename != ''""")
    # Preserve every legacy award as dated history and attach current rows to
    # the Eastern-time Sunday week that contains their original selection.
    for award in conn.execute(
        "SELECT design_id,selected_by,selected_at,is_current,current_week FROM design_of_week_awards"
    ).fetchall():
        try:
            selected = datetime.fromisoformat(str(award["selected_at"]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            selected = datetime.now(timezone.utc)
        if selected.tzinfo is None:
            selected = selected.replace(tzinfo=timezone.utc)
        local = eastern_time(selected)
        week_start = (local.date() - timedelta(days=(local.weekday() + 1) % 7)).isoformat()
        conn.execute(
            "INSERT INTO design_of_week_history(design_id,week_start,selected_by,selected_at) VALUES (?,?,?,?) "
            "ON CONFLICT(design_id,week_start) DO NOTHING",
            (award["design_id"], week_start, award["selected_by"], award["selected_at"]),
        )
        if award["is_current"] and not award["current_week"]:
            conn.execute(
                "UPDATE design_of_week_awards SET current_week=? WHERE design_id=?",
                (week_start, award["design_id"]),
            )
    _ensure_reference_data(conn)
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")
    feedback_columns = {row["name"] for row in conn.execute("PRAGMA table_info(ai_feedback)")}
    if "requester_id" not in feedback_columns:
        conn.execute("ALTER TABLE ai_feedback ADD COLUMN requester_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "question" not in feedback_columns:
        conn.execute("ALTER TABLE ai_feedback ADD COLUMN question TEXT NOT NULL DEFAULT ''")
    if "saved_at" not in feedback_columns:
        conn.execute("ALTER TABLE ai_feedback ADD COLUMN saved_at TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_requester "
        "ON ai_feedback(requester_id,saved_at,created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_expiry "
        "ON ai_feedback(saved_at,created_at)"
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone() is None:
        conn.execute("UPDATE teams SET is_founding=0,founding_rank=NULL,founding_qualified_at=NULL")
        qualifying = conn.execute(
            """SELECT t.id,MIN(d.created_at) qualified_at FROM teams t JOIN designs d ON d.team_id=t.id
                 WHERE trim(t.name)!='' AND trim(t.biography)!='' AND d.is_hidden=0 AND d.upload_status='approved'
                 GROUP BY t.id ORDER BY qualified_at,t.id LIMIT ?""", (FOUNDING_TEAM_LIMIT,)
        ).fetchall()
        for rank, row in enumerate(qualifying, 1):
            conn.execute("UPDATE teams SET is_founding=1,founding_rank=?,founding_qualified_at=? WHERE id=?",
                         (rank, row["qualified_at"], row["id"]))
        conn.execute("INSERT INTO schema_migrations(version) VALUES (3)")
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone() is None:
        contributors = conn.execute(
            """SELECT user_id,MIN(contributed_at) contributed_at FROM (
                   SELECT user_id,created_at contributed_at FROM designs WHERE is_hidden=0 AND upload_status='approved'
                   UNION ALL
                   SELECT dc.user_id,dc.credited_at FROM design_contributors dc JOIN designs d ON d.id=dc.design_id
                    WHERE d.is_hidden=0 AND d.upload_status='approved'
               ) GROUP BY user_id ORDER BY contributed_at,user_id LIMIT ?""",
            (FOUNDING_CONTRIBUTOR_LIMIT,),
        ).fetchall()
        for rank, row in enumerate(contributors, 1):
            conn.execute("UPDATE users SET founding_contributor_rank=?,founding_contributor_at=? WHERE id=? AND founding_contributor_rank IS NULL",
                         (rank, row["contributed_at"], row["user_id"]))
        conn.execute("INSERT INTO schema_migrations(version) VALUES (4)")
    _migrate_team_references(conn)
    _ensure_bigint_byte_counters(conn)
    _backfill_founding_badges(conn)
    # Migrate the original designated administrator identity to the company
    # mailbox, then transfer the role without affecting independently assigned
    # administrators.
    conn.execute(
        "UPDATE users SET email=? WHERE lower(email)=? AND lower(username)=?",
        (ADMIN_EMAIL.lower(), "hello.botfolio@gmail.com", ADMIN_USERNAME.lower()),
    )
    conn.execute("UPDATE users SET is_admin=0 WHERE lower(email)=? AND lower(username)=?", ("lawgm4@gmail.com", "lmorano2028"))
    conn.execute("UPDATE users SET is_admin=0 WHERE lower(email)=? AND lower(username)=?", ("hello.botfolio@gmail.com", ADMIN_USERNAME.lower()))
    conn.execute("UPDATE users SET is_admin=1 WHERE lower(email)=? AND lower(username)=?", (ADMIN_EMAIL.lower(), ADMIN_USERNAME.lower()))
        
    conn.commit()


def ensure_runtime_schema():
    """Add tables introduced after the original database was created.

    Gunicorn imports the application in multiple worker processes. PostgreSQL
    session advisory locking keeps those workers from interleaving schema DDL
    and data backfills during a deploy. A session lock is intentional here:
    ``executescript`` commits internally, whereas the lock must cover the whole
    migration pass.
    """
    conn = db.connect()
    locked = False
    try:
        if db.using_postgres():
            conn.execute(
                "SELECT pg_advisory_lock(?)",
                (_RUNTIME_SCHEMA_ADVISORY_LOCK,),
            )
            locked = True
        _ensure_runtime_schema(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        if locked:
            try:
                conn.execute(
                    "SELECT pg_advisory_unlock(?)",
                    (_RUNTIME_SCHEMA_ADVISORY_LOCK,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
        conn.close()


def _ensure_reference_data(conn):
    """Add missing seasons/archetypes without touching existing catalog data."""
    season_ids = {}
    for program, name, year_label, slug, sort_order in DEFAULT_SEASONS:
        conn.execute(
            "INSERT OR IGNORE INTO seasons(program,name,year_label,slug,sort_order) "
            "VALUES(?,?,?,?,?)",
            (program, name, year_label, slug, sort_order),
        )
        row = conn.execute("SELECT id FROM seasons WHERE slug=?", (slug,)).fetchone()
        season_ids[slug] = row["id"]

    for season_slug, choices in DEFAULT_ARCHETYPES.items():
        season_id = season_ids.get(season_slug) if season_slug else None
        for name, slug in choices:
            conn.execute(
                "INSERT OR IGNORE INTO archetypes(season_id,name,slug,description) "
                "VALUES(?,?,?,'')",
                (season_id, name, slug),
            )


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------

def suspension_has_expired(user):
    if not user or user["banned_at"] or not user["suspended_at"] or not user["suspended_until"]:
        return False
    try:
        expires_at = datetime.fromisoformat(user["suspended_until"].replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


def send_access_status_email(user, action, reason, duration_label=None):
    if action == "suspend":
        subject = "Your Botfolio account has been suspended"
        heading = "Account temporarily suspended"
        timing = f" for {duration_label}" if duration_label else ""
        message = (f"Your Botfolio account has been suspended{timing}.\n\nReason:\n{reason}\n\n"
                   "You will regain access automatically when the suspension ends. Contact support if you believe this action was made in error.")
        event_type = "moderation_suspension"
    elif action == "ban":
        subject = "Your Botfolio account has been banned"
        heading = "Account access removed"
        message = (f"Your Botfolio account has been banned.\n\nReason:\n{reason}\n\n"
                   "Contact support if you believe this action was made in error.")
        event_type = "moderation_ban"
    else:
        subject = "Your Botfolio account access has been restored"
        heading = "Account access restored"
        message = ("Your Botfolio account access has been restored. You may sign in and use Botfolio again.\n\n"
                   f"Administrator note:\n{reason}")
        event_type = "moderation_access_restored"
    return email_service.send_email(
        to_email=user["email"], to_name=user["username"], subject=subject,
        heading=heading, message=message, event_type=event_type,
    )


def restore_expired_suspension(user):
    conn = db.get_db()
    conn.execute(
        "UPDATE users SET suspended_at=NULL,suspended_until=NULL WHERE id=? AND banned_at IS NULL",
        (user["id"],),
    )
    conn.commit()
    send_access_status_email(user, "restore", "Your temporary suspension has ended.")
    return conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()


def _session_window():
    """The SQLite datetime modifier for a full login lifetime, e.g. '+30 days'."""
    return f"+{settings.session_lifetime_days} days"


def _session_slide_after():
    """When a live token becomes eligible to be slid forward again.

    A day short of the full window, so an active login is refreshed at most
    once a day rather than on every request it makes.
    """
    return f"+{max(settings.session_lifetime_days - 1, 0)} days"


def start_authenticated_session(user_id):
    """Create a revocable server-side login behind Flask's signed cookie."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    conn = db.get_db()
    conn.execute(
        "INSERT INTO user_sessions(token_hash,user_id,expires_at) "
        "VALUES (?,?,datetime('now', ?))",
        (token_hash, user_id, _session_window()),
    )
    conn.commit()
    session.clear()
    session.permanent = True
    session["user_id"] = user_id
    session["session_token"] = raw_token


def revoke_authenticated_session():
    """Invalidate this login in the database before deleting its cookie."""
    raw_token = session.get("session_token")
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        conn = db.get_db()
        conn.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))
        conn.commit()
    session.clear()


def record_security_event(event_type, user_id=None, details=None):
    """Persist a minimal authentication/security event for retention control."""
    conn = db.get_db()
    conn.execute(
        "INSERT INTO security_events(user_id,event_type,ip_address,details) VALUES (?,?,?,?)",
        (user_id, event_type, request.remote_addr,
         json.dumps(details or {}, separators=(",", ":"))),
    )
    conn.commit()


def current_user():
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            raw_token = session.get("session_token")
            # Unit tests that directly seed a session remain able to exercise
            # protected routes. Real requests must always present a live,
            # server-side session so a copied pre-logout cookie cannot replay.
            valid_session = app.testing and raw_token is None
            if raw_token:
                token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
                conn = db.get_db()
                valid_session = conn.execute(
                    "SELECT 1 FROM user_sessions WHERE token_hash=? AND user_id=? "
                    "AND expires_at > datetime('now')",
                    (token_hash, user_id),
                ).fetchone() is not None
                if valid_session:
                    # Sliding window: an account in active use never expires.
                    # Push the server-side expiry back to a full window to match
                    # the cookie Flask keeps re-issuing, but only once a day has
                    # passed since the last push, so an active login costs one
                    # write a day, not one per request.
                    slid = conn.execute(
                        "UPDATE user_sessions SET expires_at = datetime('now', ?) "
                        "WHERE token_hash=? AND expires_at < datetime('now', ?)",
                        (_session_window(), token_hash, _session_slide_after()),
                    )
                    if slid.rowcount:
                        conn.commit()
            if valid_session:
                g.user = db.get_db().execute(
                    "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)
                ).fetchone()
            if g.user is None:
                session.clear()
            elif suspension_has_expired(g.user):
                g.user = restore_expired_suspension(g.user)
    return g.user


def visitor_key():
    """Who a view or a download is attributed to, for counting once per person.

    A signed-in account is itself everywhere. Everyone else gets one token in
    their session, minted on first need and reused from then on, so the same
    anonymous browser is the same person to the visit counter and the download
    counter alike. Deliberately not the IP address: a school NAT would make a
    whole team look like one visitor.
    """
    viewer = current_user()
    if viewer:
        return f"u:{viewer['id']}"
    return "s:" + session.setdefault("visitor_id", secrets.token_urlsafe(16))


_VIEW_BOT_MARKERS = (
    "bot", "crawler", "spider", "slurp", "facebookexternalhit",
    "discordbot", "slackbot", "telegrambot", "whatsapp", "preview",
    "curl/", "wget/",
)


def automated_view_request():
    """Whether this request is clearly automation rather than a person.

    The real protection is architectural: page GETs never count, and the
    browser has to make an engagement POST with the session's CSRF token.
    These markers are defence in depth for rendering crawlers that execute
    JavaScript and link scanners that imitate a browser closely enough to do
    the same. They are deliberately conservative so an unusual real browser
    is not discarded merely because its user agent is unfamiliar.
    """
    agent = (request.user_agent.string or "").lower()
    purpose = " ".join((
        request.headers.get("Purpose", ""),
        request.headers.get("Sec-Purpose", ""),
        request.headers.get("X-Purpose", ""),
    )).lower()
    return any(marker in agent for marker in _VIEW_BOT_MARKERS) or any(
        marker in purpose for marker in ("prefetch", "preview", "prerender")
    )


def safe_next_target(target):
    """A `next=` value this site is willing to send someone to, or None.

    Same-site paths only. "//host" is the obvious one to refuse; "/\\host" is
    the same trick spelled differently, because browsers normalise a backslash
    to a forward slash while resolving an http(s) URL, so it arrives at the same
    off-site place. That second spelling matters here even though redirect()
    percent-encodes the backslash and defuses it: post_signup_next is not
    redirected to, it is rendered straight into an href on the onboarding page,
    where nothing encodes anything.
    """
    if not target or not target.startswith("/"):
        return None
    if target[1:2] in {"/", "\\"}:
        return None
    return target


def login_required(view=None, *, message="Please log in first."):
    """Send anyone without a usable session to sign in, then back here.

    `message` replaces the generic prompt on routes where the reason matters:
    someone who clicked Download wants to be told that downloading needs an
    account, not that some page needed a login. Usable bare (@login_required)
    or called (@login_required(message="...")).
    """
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if current_user() is None or current_user()["suspended_at"] or current_user()["banned_at"]:
                if current_user() is not None:
                    session.clear()
                    flash("This account is restricted. Contact support if you believe this is an error.", "error")
                flash(message, "error")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped
    return decorate(view) if view is not None else decorate


def verified_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user()["email_verified_at"]:
            flash("Verify your email address before uploading or commenting.", "error")
            return redirect(url_for("resend_verification"))
        return view(*args, **kwargs)
    return wrapped


# Require an administrator for moderation actions.
def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None or not current_user()["is_admin"]:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


# Create a session-bound token used by every state-changing request.
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.before_request
def protect_posts():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not supplied or not secrets.compare_digest(supplied, csrf_token()):
            abort(400, "Invalid or missing CSRF token.")


@app.before_request
def block_direct_model_access():
    """Force every model download through /designs/<id>/model.

    Flask serves the whole static/ tree, and in local-disk mode the uploaded
    3D files physically live at static/models/<uuid>. Left reachable, that URL
    hands out the exact bytes the /designs/<id>/model route guards — with no
    login check and no download recorded — which made the account requirement
    on downloads decorative: changing one path segment got you the whole
    library. Nothing in the UI links here (the viewer streams through the design
    route), so a hit on this path is either a crawler or someone routing around
    the gate. Images stay public by design; only models are gated.

    Match the *normalised* path, not the raw one. Flask's static handler
    resolves the file through werkzeug's safe_join -> posixpath.normpath, so
    /static/./models/x, /static/a/../models/x, a %2e-encoded dot, and a
    trailing-slash form all reach static/models/x — while a plain startswith on
    request.path sees the un-collapsed string and waves them straight through
    to the file. Collapsing the dot-segments first (request.path is already
    URL-decoded, so %2e is a literal '.') and folding case closes every one of
    those; forcing a single leading slash neutralises a //static double-slash.
    """
    resolved = posixpath.normpath("/" + request.path.lstrip("/")).lower()
    if resolved == "/static/models" or resolved.startswith("/static/models/"):
        abort(404)


@app.before_request
def require_account_setup():
    """Keep newly registered users in onboarding until they select a role."""
    # No endpoint means nothing matched -- an unknown path, or the right path
    # with the wrong method. Redirecting those into onboarding turns a plain
    # 404/405 into a trap: GET /logout would 302 here instead of answering.
    if request.endpoint is None:
        return None
    # Blueprints report "auth.account_setup" where the same view used to report
    # "account_setup". Matching on the bare name keeps the exemptions working on
    # both sides of that move -- miss one and the setup page redirects to itself.
    endpoint = request.endpoint.rpartition(".")[2]
    user = current_user()
    if (user and not user["onboarding_complete"]
            and endpoint not in {
                "account_setup", "account_setup_interests", "account_setup_role",
                "account_setup_team", "terms", "logout", "static",
                "learn", "learn_pathway", "learn_course", "learn_lesson",
            }):
        return redirect(url_for("account_setup"))


_last_ai_chat_purge = 0.0


@app.before_request
def purge_expired_ai_chats_periodically():
    """Enforce the three-day window even if the daily maintenance job is late."""
    global _last_ai_chat_purge
    # Liveness must not depend on schema or database availability. Railway
    # calls this before the first normal request on a fresh container.
    if request.endpoint in {"infra_metrics.healthz", "infra_metrics.readyz"}:
        return None
    now = time.monotonic()
    if app.testing or now - _last_ai_chat_purge < 3600:
        return None
    _last_ai_chat_purge = now
    conn = db.get_db()
    conn.execute(
        "DELETE FROM ai_feedback WHERE saved_at IS NULL "
        "AND created_at<datetime('now','-3 days')"
    )
    conn.commit()
    return None


@app.context_processor
def inject_globals():
    user = current_user()
    unread_notifications = 0
    if user:
        try:
            unread_notifications = _unread_notification_count(user["id"])
        except Exception:
            # This processor runs on every render for a signed-in user --
            # error.html included. Letting it raise turns one bad query into a
            # site-wide lockout with an unstyled error page, so a badge that
            # cannot be counted is shown as zero instead.
            app.logger.exception("unread notification count failed")
    return {
        "current_user": user,
        "unread_notifications": unread_notifications,
        "ai_enabled": openai_is_configured(),
        # The flag only -- never the client id or secret. A template that knows
        # whether the button should exist knows everything it needs to.
        "google_oauth_enabled": settings.google_oauth_enabled,
        "csrf_token": csrf_token,
        "max_tags": MAX_TAGS_PER_DESIGN,
        "view_count_start_label": VIEW_COUNT_START_LABEL,
        # So cards can show the "3D" badge only for a model the viewer can
        # really open, rather than one it would refuse or choke on.
        "model_is_viewable": model_is_viewable,
    }


def _unread_notification_count(user_id):
    """Unread notifications plus pending team invitations/requests, as one number."""
    return db.get_db().execute(
        """SELECT
             (SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL) +
             (SELECT COUNT(*) FROM team_membership_requests r
               JOIN teams t ON t.id=r.team_id
              WHERE r.status='pending' AND
                    ((r.kind='invitation' AND r.user_id=?) OR
                     (r.kind='request' AND t.owner_id=?))) AS n""",
        (user_id, user_id, user_id),
    ).fetchone()["n"]


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def normalize_tag(name):
    """The stored form of a tag: lowercase, one space between words. Storage
    stays lowercase so matching is simple; `display_tag` handles presentation."""
    return re.sub(r"\s+", " ", name.strip().lower())


# Words that look wrong title-cased, so they get their own spelling on screen.
TAG_ACRONYMS = {"2d", "3d", "abs", "api", "cad", "cnc", "cpu", "dc", "frc", "ftc",
                "glb", "gpu", "imu", "obj", "petg", "pid", "pla", "pwm", "rev",
                "stl", "tpu"}

def display_tag(name):
    """How a tag is shown: capitalised, acronyms in caps. Presentation only —
    links and searches keep using the stored lowercase spelling, so this never
    has to round-trip."""
    def word(match):
        w = match.group(0)
        return w.upper() if w in TAG_ACRONYMS else w[:1].upper() + w[1:]

    # Substituting each alphanumeric run rather than splitting on spaces, so
    # 'four-bar' capitalises both halves instead of just the first.
    return re.sub(r"[a-z0-9]+", word, (name or "").lower())


# Templates render tags through this; the raw name still goes in hrefs.
app.add_template_filter(display_tag, "tagcase")


def review_excerpt(text, max_chars=280):
    """Keep the collapsed AI review to at most two short sentences."""
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    excerpt = " ".join(sentences[:2]).strip()
    if len(excerpt) <= max_chars:
        return excerpt
    shortened = excerpt[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    return shortened + "…"


app.add_template_filter(review_excerpt, "review_excerpt")


def singularize(word):
    """Enough of a plural rule to stop 'intake' and 'intakes' being two tags.

    Deliberately conservative at the end: words ending -ss, -is or -us are left
    alone, so 'chassis' does not quietly become 'chassi' and collide with
    something else."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
        return word[:-1]
    return word


def tag_key(name):
    """The fingerprint two spellings have to share to count as the same tag.

    Case, spacing and punctuation are dropped and a trailing plural is folded
    away, so 'Box Tube', 'box-tube', 'boxtube ' and 'Box Tubes' all resolve to
    one existing tag rather than four. Stored on the row and kept unique, which
    is what makes the merge in `consolidate_tags` stick."""
    return "".join(singularize(w) for w in re.findall(r"[a-z0-9]+", normalize_tag(name)))


def find_tag(conn, name):
    """The existing tag this name refers to, if there is one."""
    return conn.execute(
        "SELECT id, name FROM tags WHERE key = ?", (tag_key(name),)
    ).fetchone()


def consolidate_tags(conn):
    """Fold tags that differ only in spelling into a single row, then keep them
    that way with a unique index on the fingerprint.

    Runs on every start: it is how spellings that predate the fingerprint, or
    that a widened rule newly considers equal, get merged. Whichever row the
    most designs already use survives; the oldest breaks a tie."""
    groups = {}
    names = {}
    for row in conn.execute("SELECT id, name FROM tags ORDER BY id"):
        groups.setdefault(tag_key(row["name"]), []).append(row["id"])
        names[row["id"]] = row["name"]

    usage = dict(conn.execute(
        "SELECT tag_id, COUNT(*) FROM design_tags GROUP BY tag_id"
    ).fetchall())

    for key, ids in groups.items():
        winner = max(ids, key=lambda tag_id: (usage.get(tag_id, 0), -tag_id))
        for loser in ids:
            if loser == winner:
                continue
            # Copy across before deleting, not after: tag_votes has a composite
            # foreign key into design_tags, so the winner's assignment row has
            # to exist before its votes can point at it. OR IGNORE covers a
            # design (or voter) that already carried both spellings.
            conn.execute(
                "INSERT OR IGNORE INTO design_tags (design_id, tag_id, added_by, created_at, low_score_since) "
                "SELECT design_id, ?, added_by, created_at, low_score_since FROM design_tags WHERE tag_id = ?",
                (winner, loser),
            )
            conn.execute(
                "INSERT OR IGNORE INTO tag_votes (user_id, design_id, tag_id, value, created_at) "
                "SELECT user_id, design_id, ?, value, created_at FROM tag_votes WHERE tag_id = ?",
                (winner, loser),
            )
            # The loser's own rows go with it, by ON DELETE CASCADE.
            conn.execute("DELETE FROM tags WHERE id = ?", (loser,))
        # Normalised on the way past, so a row stored before the rule existed
        # ends up in the same lowercase form as everything else. Two names that
        # normalise alike also fingerprint alike, so this cannot collide with
        # the UNIQUE on name — they were merged just above.
        conn.execute("UPDATE tags SET name = ?, key = ? WHERE id = ?",
                     (normalize_tag(names[winner]), key, winner))

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_key ON tags(key)")


# Down here rather than beside the function: the migration folds duplicate tags
# together, which needs the fingerprint defined above.
if db.db_is_initialized():
    ensure_runtime_schema()


# Accept only complete HTTP(S) URLs without embedded credentials.
def clean_url(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ValueError("Links must be complete http:// or https:// URLs.")
    return raw


@app.template_filter("safe_report_url")
def safe_report_url(raw):
    """Return a reported location only when it is a genuine web link.

    A content report's "location" may be a real URL or just a bare Content ID,
    and /report has no login gate, so an anonymous reporter can put anything in
    it. Rendered straight into an href, a value like ``javascript:...`` would
    execute when a moderator clicks it — Jinja autoescaping escapes HTML but not
    a URL scheme. This yields the value only for http(s) URLs; the template
    shows anything else as plain (escaped) text instead of a live link.
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw
    return ""


def _unique_filename(original, fallback_ext):
    ext = Path(secure_filename(original or "")).suffix.lower() or fallback_ext
    return f"{uuid.uuid4().hex}{ext}"


def save_image_upload(file_storage):
    """Validate and store an uploaded image. Returns a filename or raises ValueError."""
    ext = Path(secure_filename(file_storage.filename or "")).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"Images must be one of: {', '.join(sorted(IMAGE_EXTENSIONS))}."
        )

    raw = file_storage.read()
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"That image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    if not raw:
        raise ValueError("That image file was empty.")

    return _store_image_bytes(raw)


def save_preview_data_url(data_url):
    """Store a render captured from the 3D viewer.

    This arrives as a user-controlled string in a form field, so it is never
    trusted: the prefix is checked, the payload is base64-decoded, and the
    bytes are re-opened with Pillow before anything is written to disk.
    """
    match = re.match(r"^data:image/(png|jpeg);base64,", data_url)
    if not match:
        raise ValueError("The captured preview was not a valid image.")

    try:
        raw = base64.b64decode(data_url[match.end():], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The captured preview could not be decoded.")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("The captured preview was too large.")

    return _store_image_bytes(raw)


class _ImageTooLarge(Exception):
    """Raised when an image's pixel count exceeds MAX_IMAGE_PIXELS.

    A plain exception, not a ValueError, so it is caught by its own handler in
    sanitize_image_bytes and mapped to the "too large" message rather than the
    generic "could not be read" one — the broad ValueError/OSError clause never
    sees it.
    """


def sanitize_image_bytes(raw):
    """Decode and re-encode an image without EXIF, GPS, or other metadata."""
    try:
        with Image.open(io.BytesIO(raw)) as img:
            # Reject an oversized image from its header, before decoding a single
            # pixel. Pillow only *raises* DecompressionBombError above 2x
            # MAX_IMAGE_PIXELS — between 1x and 2x it emits a non-fatal warning
            # and decodes anyway — so a 99 MP file (a ~100 KB PNG, well under
            # the 8 MB byte cap) would otherwise allocate its full ~280 MB RGB
            # buffer below. img.size is read from the header, so this is free.
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                raise _ImageTooLarge()
            # Apply orientation while EXIF still exists, then construct a new
            # pixel-only image. Saving without exif/icc_profile arguments
            # guarantees metadata from the source is not copied through.
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            if max(img.size) > MAX_IMAGE_EDGE:
                img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            clean = io.BytesIO()
            img.save(clean, format="JPEG", quality=88)
    except (Image.DecompressionBombError, _ImageTooLarge):
        # Our header check (the 1x-2x band) and Pillow's own guard (the >2x
        # band, which it raises from either open() or load()) both land here.
        # DecompressionBombError is neither OSError nor ValueError, so without
        # this clause it would slip past the handler below and every route's
        # guard and surface as an unhandled 500.
        raise ValueError("That image is too large to process.")
    except (OSError, ValueError):
        raise ValueError("That file could not be read as an image.")
    return clean.getvalue()


def _store_image_bytes(raw):
    """Sanitize, moderate, and store a public image as a metadata-free JPEG."""
    clean = sanitize_image_bytes(raw)
    moderate_public_content(image_bytes=[clean], use_api=not app.testing)
    filename = f"{uuid.uuid4().hex}.jpg"
    with Image.open(io.BytesIO(clean)) as img:
        infra_storage.save_image("uploads", filename, img, format="JPEG", quality=88)
    return filename


def _safe_upload_size(filename):
    """Bytes stored for an uploaded image, or 0 when it cannot be read.

    Only used to adjust storage counters, which must never crash the user
    action they are bookkeeping for. A cover can be absent from the uploads
    store — a seeded demo image that only lives in the repo, or a file already
    cleaned up — so a missing object (FileNotFoundError on disk, a 404 from S3)
    counts as zero rather than raising. The running total self-heals from the
    per-design storage_bytes sum if it ever drifts. Same reasoning as
    infra_storage.delete() never raising.
    """
    if not filename:
        return 0
    try:
        return infra_storage.size("uploads", filename)
    except Exception as exc:  # noqa: BLE001 — any storage miss is non-fatal here
        logging.getLogger("botfolio").warning(
            "could not size upload %s (%s); counting as 0 bytes",
            filename, type(exc).__name__,
        )
        return 0


def save_model_upload(file_storage):
    ext = Path(secure_filename(file_storage.filename or "")).suffix.lower()
    if ext not in MODEL_EXTENSIONS:
        raise ValueError(
            f"3D models must be one of: {', '.join(sorted(MODEL_EXTENSIONS))}."
        )

    raw = file_storage.read()
    if len(raw) > MAX_INLINE_MODEL_BYTES:
        raise ValueError(
            "Models over 350 MB require direct object-storage uploads."
        )
    if not raw:
        raise ValueError("That model file was empty.")

    if not valid_model_content(ext, raw[:4096], len(raw)):
        raise ValueError(f"The uploaded file was not a valid {MODEL_FORMATS_PHRASE} model.")

    filename = _unique_filename(file_storage.filename, ".stl")
    infra_storage.save("models", filename, raw)
    return filename, len(raw), hashlib.sha256(raw).hexdigest()


def valid_model_content(extension, prefix, actual_size):
    """Validate the basic structure of the launch allowlisted model formats."""
    if extension == ".obj":
        try:
            text_prefix = prefix.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return bool(re.search(r"(?m)^\s*(?:v|f|o|g|mtllib)\s+", text_prefix))
    if extension == ".stl":
        ascii_stl = prefix.lstrip().lower().startswith(b"solid") and b"facet" in prefix.lower()
        binary_stl = False
        if len(prefix) >= 84:
            triangles = int.from_bytes(prefix[80:84], "little")
            binary_stl = triangles > 0 and 84 + (triangles * 50) == actual_size
        return ascii_stl or binary_stl
    if extension == ".glb":
        # glTF binary: a 12-byte header of the magic "glTF", a uint32 version
        # (2), then a uint32 total length that must match the file exactly.
        if len(prefix) < 12 or prefix[:4] != b"glTF":
            return False
        version = int.from_bytes(prefix[4:8], "little")
        total_length = int.from_bytes(prefix[8:12], "little")
        return version == 2 and total_length == actual_size
    if extension in CAD_SOURCE_EXTENSIONS:
        # ISO 10303-21 opens with its own version tag and then a HEADER
        # section. The comparison stays on bytes because a part 21 file is
        # plain text but not reliably in one encoding, and the structure is all
        # that is being asked about. A byte order mark is tolerated: a fair
        # number of Windows CAD exporters write one.
        head = prefix[3:] if prefix.startswith(b"\xef\xbb\xbf") else prefix
        head = head.lstrip().upper()
        return bool(re.match(rb"ISO-10303-21\s*;", head)) and bool(
            re.search(rb"HEADER\s*;", head)
        )
    return False


def is_cad_source(filename):
    """Whether a stored model is CAD source rather than a drawable mesh."""
    return bool(filename) and Path(filename).suffix.lower() in CAD_SOURCE_EXTENSIONS


def model_is_viewable(filename, size_bytes=None):
    """Whether the browser viewer can open a stored model.

    Two things disqualify one, and they land on the same download-only path: a
    format the viewer has no loader for — STEP needs a CAD kernel before it is
    triangles at all — and a mesh so large that parsing it would take the tab
    down with it. Cards, the design page, and the streaming route all ask here
    rather than each keeping a copy of the rule.
    """
    if not filename:
        return False
    if Path(filename).suffix.lower() not in VIEWABLE_MODEL_EXTENSIONS:
        return False
    return not size_bytes or size_bytes <= MAX_VIEW_MODEL_BYTES


# Roughly a school bus, which no FTC part approaches. It is here to catch a
# slipped decimal point rather than to express a rule anyone will meet.
MAX_DIMENSION_IN = 1000


def dimension_error(raws, values):
    """Check the optional length/width/height triple, returning a message or None.

    The three are one datum, not three: a bounding box means nothing with a
    side missing, and the design page only prints the row when it has all
    three. So they are all-or-nothing, unlike the motor and servo counts in
    the same fieldset, which really are independent and optional one by one.
    Leaving the whole triple blank is fine — plenty of designs are shared
    before anyone has measured them.

    Takes the raw strings as well as the parsed floats because parsing cannot
    tell "left blank" from "not a number", and only the first is allowed.
    """
    if not any(raws):
        return None
    if not all(raws):
        return "Enter all three dimensions, or leave length, width, and height blank."
    if any(value is None or not 0 < value <= MAX_DIMENSION_IN for value in values):
        return f"Each dimension must be a positive number up to {MAX_DIMENSION_IN} inches."
    return None


def clean_camera_json(raw):
    """Reduce the viewer's camera state to two arrays of three finite numbers.

    This value is echoed back into a <script> block on the design page, and it
    arrives in a form field, so it is rebuilt from scratch here rather than
    stored as sent. Anything unexpected is dropped.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    cleaned = {}
    for key in ("position", "target"):
        value = data.get(key)
        if (isinstance(value, list) and len(value) == 3
                and all(isinstance(n, (int, float)) and not isinstance(n, bool)
                        and math.isfinite(n) for n in value)):
            cleaned[key] = [float(n) for n in value]

    return json.dumps(cleaned) if "position" in cleaned else None


def delete_asset(folder, filename):
    """Remove a stored file. Takes UPLOAD_DIR or MODEL_DIR, as it always has.

    The directory argument is now translated to a storage bucket name so the
    eight existing call sites did not have to change. infra.storage handles the
    "missing file must not block deleting the row" case that used to live here.
    """
    if not filename:
        return
    infra_storage.delete("models" if folder == MODEL_DIR else "uploads", filename)


def tags_for_design(design_id, viewer_id=None):
    """Tags with their vote scores, best first, plus this viewer's own vote."""
    return db.get_db().execute(
        """
        SELECT t.id, t.name,
               COALESCE(SUM(v.value), 0) AS score,
               (SELECT value FROM tag_votes
                 WHERE user_id = ? AND design_id = dt.design_id AND tag_id = t.id
               ) AS my_vote
          FROM design_tags dt
          JOIN tags t ON t.id = dt.tag_id
          LEFT JOIN tag_votes v
                 ON v.design_id = dt.design_id AND v.tag_id = dt.tag_id
         WHERE dt.design_id = ?
         GROUP BY t.id, t.name, dt.design_id
         ORDER BY score DESC, t.name ASC
        """,
        (viewer_id, design_id),
    ).fetchall()


def attach_tag(design_id, raw_name, user_id):
    """Add a tag to a design, creating the tag itself if it is genuinely new."""
    name = normalize_tag(raw_name)
    if not name or len(name) > MAX_TAG_LENGTH:
        raise ValueError(f"Tags must be 1-{MAX_TAG_LENGTH} characters.")

    conn = db.get_db()
    row = find_tag(conn, name)
    if row and conn.execute("SELECT 1 FROM design_tags WHERE design_id=? AND tag_id=?", (design_id, row["id"])).fetchone():
        return None
    count = conn.execute("SELECT COUNT(*) n FROM design_tags WHERE design_id=?", (design_id,)).fetchone()["n"]
    if count >= MAX_TAGS_PER_DESIGN:
        raise ValueError(f"A design can have at most {MAX_TAGS_PER_DESIGN} tags.")
    if row is None:
        recent = conn.execute("SELECT COUNT(*) n FROM tags WHERE created_by=? AND created_at >= datetime('now', '-1 hour')", (user_id,)).fetchone()["n"]
        if recent >= NEW_TAG_LIMIT_PER_HOUR:
            raise ValueError("You are creating tags too quickly. Try an existing tag or wait an hour.")
        cur = conn.execute(
            "INSERT INTO tags (name, key, created_by) VALUES (?, ?, ?)",
            (name, tag_key(name), user_id),
        )
        tag_id = cur.lastrowid
    else:
        tag_id = row["id"]

    conn.execute(
        "INSERT OR IGNORE INTO design_tags (design_id, tag_id, added_by) "
        "VALUES (?, ?, ?)",
        (design_id, tag_id, user_id),
    )
    return tag_id


# Mark questionable assignments for administrator review; votes never delete tags.
def cleanup_low_score_tags(conn, design_id=None, tag_id=None):
    where, params = [], []
    if design_id is not None:
        where.append("dt.design_id=?"); params.append(design_id)
    if tag_id is not None:
        where.append("dt.tag_id=?"); params.append(tag_id)
    clause = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(f"SELECT dt.design_id,dt.tag_id,dt.low_score_since,COALESCE(SUM(v.value),0) score FROM design_tags dt LEFT JOIN tag_votes v ON v.design_id=dt.design_id AND v.tag_id=dt.tag_id {clause} GROUP BY dt.design_id,dt.tag_id", params).fetchall()
    for row in rows:
        if row["score"] <= TAG_LOW_SCORE:
            if not row["low_score_since"]:
                conn.execute("UPDATE design_tags SET low_score_since=datetime('now') WHERE design_id=? AND tag_id=?", (row["design_id"], row["tag_id"]))
        elif row["low_score_since"]:
            conn.execute("UPDATE design_tags SET low_score_since=NULL WHERE design_id=? AND tag_id=?", (row["design_id"], row["tag_id"]))
    return 0


def qualify_founding_team(conn, team_id):
    """Award a rank only to a claimed team with confirmed team work."""
    if not team_id:
        return False
    team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    # The original Founding 50 is an FTC launch program. FRC teams join the
    # same directory, but do not rewrite that piece of Botfolio history.
    if team and team["program"] != "ftc":
        return False
    if not team or team["founding_rank"]:
        return bool(team and team["founding_rank"])
    has_design = conn.execute(
        """SELECT 1 FROM designs d
             WHERE d.team_id=? AND d.is_hidden=0 AND d.upload_status='approved'
               AND (d.team_attribution_accepted=1 OR EXISTS (
                    SELECT 1 FROM memberships m
                     WHERE m.team_id=d.team_id AND m.user_id=d.user_id))
             LIMIT 1""",
        (team_id,),
    ).fetchone()
    if team["profile_status"] != "claimed" or not team["name"].strip() or not has_design:
        return False
    claimed = conn.execute("SELECT COUNT(*) n FROM teams WHERE founding_rank IS NOT NULL").fetchone()["n"]
    if claimed >= FOUNDING_TEAM_LIMIT:
        return False
    rank = conn.execute(
        "SELECT COALESCE(MAX(founding_rank),0)+1 rank FROM teams"
    ).fetchone()["rank"]
    conn.execute(
        "UPDATE teams SET is_founding=1,founding_rank=?,founding_qualified_at=datetime('now') WHERE id=? AND founding_rank IS NULL",
        (rank, team_id),
    )
    return True


def qualify_founding_contributor(conn, user_id):
    """Permanently award a rank to one of the first 100 design uploaders."""
    user = conn.execute("SELECT founding_contributor_rank FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["founding_contributor_rank"]:
        return bool(user and user["founding_contributor_rank"])
    uploaded = conn.execute(
        "SELECT 1 FROM designs WHERE user_id=? AND is_hidden=0 AND upload_status='approved' LIMIT 1",
        (user_id,),
    ).fetchone()
    if not uploaded:
        return False
    claimed = conn.execute("SELECT COUNT(*) n FROM users WHERE founding_contributor_rank IS NOT NULL").fetchone()["n"]
    if claimed >= FOUNDING_CONTRIBUTOR_LIMIT:
        return False
    conn.execute(
        "UPDATE users SET founding_contributor_rank=?,founding_contributor_at=datetime('now') WHERE id=? AND founding_contributor_rank IS NULL",
        (claimed + 1, user_id),
    )
    return True


def save_design_contributors(conn, design_id, usernames, roles):
    """Replace contributor credits using registered usernames supplied by the uploader."""
    conn.execute("DELETE FROM design_contributors WHERE design_id=?", (design_id,))
    unknown = []
    for username, role in list(zip(usernames, roles))[:12]:
        username = username.strip()
        if not username:
            continue
        person = conn.execute("SELECT id FROM users WHERE lower(username)=lower(?) AND deleted_at IS NULL", (username,)).fetchone()
        if not person:
            unknown.append(username)
            continue
        role = role if role in CONTRIBUTOR_ROLES else None
        conn.execute(
            "INSERT INTO design_contributors(design_id,user_id,role) VALUES (?,?,?)",
            (design_id, person["id"], role),
        )
    if unknown:
        raise ValueError("These contributor usernames are not registered: " + ", ".join(unknown))


# --------------------------------------------------------------------------
# Public pages
# --------------------------------------------------------------------------

def design_week_start(moment=None):
    """Return the local Sunday that owns a Design-of-the-Week selection."""
    local = eastern_time(moment or datetime.now(timezone.utc))
    days_since_sunday = (local.weekday() + 1) % 7
    return (local.date() - timedelta(days=days_since_sunday)).isoformat()

@app.route("/")
def index():
    conn = db.get_db()
    current_award_week = design_week_start()
    design_select = """
        SELECT d.*, u.username, s.name AS season_name,
               tm.number AS team_number, tm.name AS team_name,
               tm.program AS team_program,
               (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
               (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count,
               (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count
          FROM designs d
          JOIN users u ON u.id = d.user_id
          LEFT JOIN seasons s ON s.id = d.season_id
          LEFT JOIN teams tm ON tm.id = d.team_id
         WHERE d.is_hidden = 0
    """
    # This section promises the newest designs, so order it strictly by publish
    # time. The gallery can keep its curated shelf order, but applying that
    # order here allowed older team uploads to displace newer designs.
    designs = conn.execute(
        design_select + """
         ORDER BY d.created_at DESC, d.id DESC
         LIMIT 12
        """
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM designs").fetchone()["n"]
    designs_of_week = conn.execute(
        design_select.replace(
            "WHERE d.is_hidden = 0",
            "JOIN design_of_week_awards dw ON dw.design_id=d.id WHERE d.is_hidden = 0",
        ) + " AND dw.is_current=1 AND dw.current_week=? ORDER BY dw.selected_at DESC LIMIT 4",
        (current_award_week,),
    ).fetchall()
    # The hero carousel shows only the designs actually awarded Design of the
    # Week (most recent award first), and only those with a preview image to
    # show. It never falls back to designs that were not awarded. One award row
    # per design (design_id is the award PK), so no GROUP BY is needed — this
    # mirrors the designs_of_week query above and stays Postgres-safe.
    hero_slides = conn.execute(
        design_select.replace(
            "WHERE d.is_hidden = 0",
            "JOIN design_of_week_awards dw ON dw.design_id=d.id WHERE d.is_hidden = 0",
        ) + """
           AND dw.is_current=1 AND dw.current_week=?
           AND d.image_filename IS NOT NULL AND d.image_filename <> ''
         ORDER BY dw.selected_at DESC, d.id DESC
         LIMIT 9
        """,
        (current_award_week,),
    ).fetchall()
    return render_template("index.html", designs=designs, total=total,
                           designs_of_week=designs_of_week, hero_slides=hero_slides)


@app.route("/founding-50")
def founding_50():
    teams = db.get_db().execute(
        "SELECT * FROM teams WHERE founding_rank IS NOT NULL ORDER BY founding_rank"
    ).fetchall()
    return render_template("founding_50.html", teams=teams, limit=FOUNDING_TEAM_LIMIT)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/help", endpoint="help")
def help_page():
    """How Botfolio works, plus the contact directory. The "how it works" steps
    used to live on the home page; they moved here alongside the email channels
    so there is one place to learn the flow and find the right inbox."""
    return render_template(
        "help.html",
        support_email=SUPPORT_EMAIL, privacy_email=PRIVACY_EMAIL,
        security_email=SECURITY_EMAIL, copyright_email=COPYRIGHT_EMAIL,
        legal_email=LEGAL_EMAIL,
    )


# --------------------------------------------------------------------------
@app.route("/robots.txt")
def robots():
    """Keep crawlers off the routes that cost bandwidth or count as activity.

    There was no robots.txt at all, so every crawler that walked a design page
    followed the download link too — a GET that transfers a multi-GB model and,
    until now, registered as somebody downloading it. Search engines have no
    reason to index a CAD file or a raw model stream, and the pages worth
    finding are all still open.
    """
    rules = ["User-agent: *", "Disallow: /designs/*/download",
             "Disallow: /designs/*/cad", "Disallow: /designs/*/model",
             "", "Sitemap: " + url_for("sitemap", _external=True)]
    return Response("\n".join(rules) + "\n", mimetype="text/plain")


@app.route("/sitemap.xml")
@ratelimit.limit("sitemap", 60, 3600, methods=None)
def sitemap():
    """A map of the pages worth indexing, handed to search engines directly.

    Without one, a crawler only finds a page by following a link to it, so a
    brand-new design can sit undiscovered for a while. This lists the stable
    public pages plus every approved, visible design, team, and contributor
    profile, so they get indexed sooner. Hidden and unapproved designs are
    left out on purpose.

    Building it touches three tables and calls url_for once per row, so the
    rendered XML is cached for an hour and the route is rate limited: a public,
    uncached endpoint that scans tables on every hit is an easy amplification
    target, and a sitemap that lags real content by an hour costs nothing.
    """
    cached = cache.get("sitemap:xml")
    if cached is not None:
        return Response(cached, mimetype="application/xml")

    conn = db.get_db()
    pages = []

    def add(endpoint, lastmod=None, **values):
        # Hard stop under the 50k-URLs-per-file protocol limit, whatever the
        # per-section caps and data growth add up to.
        if len(pages) >= SITEMAP_URL_LIMIT:
            return
        pages.append({"loc": url_for(endpoint, _external=True, **values),
                      "lastmod": (lastmod or "")[:10] or None})

    for endpoint in ("index", "gallery", "tag_directory", "team_list", "about", "learn",
                     "terms", "privacy", "community_rules", "copyright_policy"):
        add(endpoint)

    from academy.catalog import CATALOG
    for platform, courses in CATALOG.items():
        add("learn_pathway", platform=platform)
        for course in courses:
            if course["status"] == "Live":
                add("learn_course", platform=platform, course_slug=course["slug"])

    for row in conn.execute(
        "SELECT id, updated_at FROM designs "
        "WHERE is_hidden=0 AND upload_status='approved' "
        "ORDER BY id DESC LIMIT ?", (SITEMAP_MAX,)
    ).fetchall():
        add("design_detail", row["updated_at"], design_id=row["id"])

    for row in conn.execute(
        "SELECT program,number FROM teams ORDER BY program,number LIMIT ?", (SITEMAP_MAX,)
    ).fetchall():
        add("team_detail", program=row["program"], number=row["number"])

    for row in conn.execute(
        "SELECT DISTINCT u.username FROM users u "
        "JOIN designs d ON d.user_id = u.id "
        "WHERE d.is_hidden = 0 AND d.upload_status = 'approved' "
        "ORDER BY u.username LIMIT ?", (SITEMAP_MAX,)
    ).fetchall():
        add("profile", username=row["username"])

    body = render_template("sitemap.xml", pages=pages)
    cache.put("sitemap:xml", body, seconds=3600)
    return Response(body, mimetype="application/xml")


@app.route("/terms")
def terms():
    return render_template("terms.html", terms_version=TERMS_VERSION)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", privacy_version=PRIVACY_VERSION)


@app.route("/community-rules")
def community_rules():
    return render_template("community_rules.html")


@app.route("/copyright")
def copyright_policy():
    return render_template("copyright.html")


REPORT_REASON_GROUPS = [
    ("Highest priority — immediate review", [
        ("threat", "Threat or serious safety concern"),
        ("youth_safety", "Minor exploitation or youth-safety concern"),
        ("intimate", "Intimate or nonconsensual imagery"),
        ("privacy_danger", "Dangerous disclosure of personal information"),
        ("malware", "Malware or security compromise"),
    ]),
    ("High priority", [
        ("confidential", "Confidential or stolen files"),
        ("harassment", "Serious harassment or bullying"),
        ("impersonation", "Impersonation or false affiliation"),
        ("copyright", "Copyright or ownership issue"),
        ("spam", "Spam, scam, or malicious link"),
        ("manipulation", "Manipulation of likes, tags, or reports"),
    ]),
    ("Other reports", [
        ("unsafe", "Other inappropriate or unsafe content"),
        ("privacy", "Other personal or private information"),
        ("other", "Other"),
    ]),
]
REPORT_REASONS = {
    value: label for _group, reasons in REPORT_REASON_GROUPS for value, label in reasons
}
CRITICAL_REPORT_REASONS = {
    "threat", "youth_safety", "intimate", "privacy_danger", "malware"
}
HIGH_REPORT_REASONS = {
    "confidential", "harassment", "impersonation", "copyright", "spam", "manipulation"
}


@app.route("/report", methods=["GET", "POST"])
@ratelimit.limit("report", 10, 3600)
def report_content():
    if request.method == "POST":
        content_type = (request.form.get("content_type") or "other").strip()[:30]
        content_id = (request.form.get("content_id") or "").strip()[:120]
        content_url = (request.form.get("content_url") or "").strip()[:1000]
        reason = request.form.get("reason") or ""
        description = (request.form.get("description") or "").strip()[:5000]
        reporter_email = (request.form.get("email") or "").strip()[:254]
        error = None
        if reason not in REPORT_REASONS:
            error = "Choose a reason for the report."
        elif not content_url:
            error = "Provide the URL or content ID being reported."
        elif len(description) < 10:
            error = "Please briefly explain the issue."
        elif not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", reporter_email):
            error = "Enter a valid email address."
        if error:
            flash(error, "error")
        else:
            urgent = int(reason in CRITICAL_REPORT_REASONS)
            priority = 3 if urgent else 2 if reason in HIGH_REPORT_REASONS else 1
            conn = db.get_db()
            cursor = conn.execute(
                "INSERT INTO content_reports(reporter_id,content_type,content_id,content_url,reason,description,reporter_email,urgent,priority) VALUES (?,?,?,?,?,?,?,?,?)",
                (current_user()["id"] if current_user() else None, content_type,
                 content_id or None, content_url, reason, description,
                 reporter_email, urgent, priority),
            )
            conn.commit()
            message = (f"Report #{cursor.lastrowid}\nType: {content_type}\n"
                       f"Content: {content_id}\nURL: {content_url}\n"
                       f"Reason: {REPORT_REASONS[reason]}\nFrom: {reporter_email}\n\n{description}")
            email_service.send_email(
                to_email=SUPPORT_EMAIL, to_name="Botfolio moderation",
                subject=f"[Botfolio report #{cursor.lastrowid}] {REPORT_REASONS[reason]}",
                heading="New content report", message=message,
                event_type="content_report", reply_to=reporter_email,
            )
            if urgent:
                email_service.send_email(
                    to_email=SECURITY_EMAIL, to_name="Botfolio security",
                    subject=f"URGENT P1: {REPORT_REASONS[reason]} — report #{cursor.lastrowid}",
                    heading="Highest-priority safety report", message=message,
                    event_type="urgent_content_report", reply_to=reporter_email,
                )
            flash("Thank you. Your report has been submitted to Botfolio for review.", "success")
            return redirect(url_for("report_content"))
    return render_template(
        "report.html", reasons=REPORT_REASONS, reason_groups=REPORT_REASON_GROUPS,
        content_type=(request.args.get("type") or "other")[:30],
        content_id=(request.args.get("id") or "")[:120],
        content_url=(request.args.get("url") or "")[:1000],
        security_email=SECURITY_EMAIL, copyright_email=COPYRIGHT_EMAIL,
    )


@app.route("/contact", methods=["GET", "POST"])
# Sends mail to the admin address. Uncapped, it is a spam relay.
@ratelimit.limit("contact", 5, 3600)
def contact():
    issue_types = {
        "account": "Account help",
        "technical": "Technical problem",
        "content": "Design or content question",
        "safety": "Safety or moderation concern",
        "partnership": "Partnership or sponsorship",
        "other": "Other",
    }
    if request.method == "POST":
        sender_email = (request.form.get("email") or "").strip()[:254]
        subject = (request.form.get("subject") or "").strip()[:120]
        issue = request.form.get("issue") or ""
        message = (request.form.get("message") or "").strip()[:5000]
        if request.form.get("website"):
            return redirect(url_for("contact"))

        error = None
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sender_email):
            error = "Enter a valid email address."
        elif not subject:
            error = "Add a subject line."
        elif issue not in issue_types:
            error = "Choose the type of issue."
        elif len(message) < 10:
            error = "Your message must be at least 10 characters."
        elif session.get("contact_sent_at") and session["contact_sent_at"] > int(time.time()) - 300:
            error = "Please wait a few minutes before sending another message."

        if error:
            flash(error, "error")
        else:
            sent = email_service.send_email(
                to_email=SUPPORT_EMAIL,
                to_name="Botfolio team",
                subject=f"[Botfolio {issue_types[issue]}] {subject}",
                heading=f"New contact request: {issue_types[issue]}",
                message=f"From: {sender_email}\n\n{message}",
                event_type="contact_form",
                reply_to=sender_email,
            )
            if sent:
                session["contact_sent_at"] = int(time.time())
                flash("Your message was sent to Botfolio.", "success")
                return redirect(url_for("contact"))
            flash("We could not send your message right now. Please email us directly.", "error")

    return render_template(
        "contact.html", contact_email=SUPPORT_EMAIL, issue_types=issue_types,
        privacy_email=PRIVACY_EMAIL, security_email=SECURITY_EMAIL,
        copyright_email=COPYRIGHT_EMAIL, legal_email=LEGAL_EMAIL,
    )


# How long the search box will wait on the FTC registry before falling back to
# just the local (claimed) teams. Short, because it runs on the typeahead path.
REGISTRY_SEARCH_TIMEOUT = 2.5


def site_search_results(conn, raw_query, limit=6):
    """Return small, categorized public-site search results."""
    query = (raw_query or "").strip()[:254]
    groups = [
        {"key": "designs", "label": "Designs", "items": []},
        {"key": "people", "label": "People", "items": []},
        {"key": "teams", "label": "Teams", "items": []},
        {"key": "tags", "label": "Tags", "items": []},
        {"key": "pages", "label": "Pages", "items": []},
    ]
    if not query:
        return groups

    pattern = f"%{query}%"
    designs = conn.execute(
        """SELECT d.*,u.username,s.name season_name,
                  tm.number team_number,tm.name team_name,
                  (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
                  (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count,
                  (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count
             FROM designs d JOIN users u ON u.id=d.user_id
             LEFT JOIN seasons s ON s.id=d.season_id
             LEFT JOIN teams tm ON tm.id=d.team_id
            WHERE d.is_hidden=0
              AND (lower(d.title) LIKE lower(?) OR lower(d.description) LIKE lower(?))
            ORDER BY CASE WHEN lower(d.title)=lower(?) THEN 0
                          WHEN lower(d.title) LIKE lower(?) THEN 1 ELSE 2 END,
                     d.created_at DESC,d.id DESC
            LIMIT ?""",
        (pattern, pattern, query, f"{query}%", limit),
    ).fetchall()
    groups[0]["items"] = [
        {"title": row["title"], "subtitle": f"Design by {row['username']}",
         "url": url_for("design_detail", design_id=row["id"]),
         "design": dict(row)}
        for row in designs
    ]

    people = conn.execute(
        """SELECT username,tagline
             FROM users
            WHERE deleted_at IS NULL AND suspended_at IS NULL AND banned_at IS NULL
              AND (lower(username) LIKE lower(?) OR lower(tagline) LIKE lower(?)
                   OR lower(specialties) LIKE lower(?))
            ORDER BY CASE WHEN lower(username)=lower(?) THEN 0
                          WHEN lower(username) LIKE lower(?) THEN 1 ELSE 2 END,
                     lower(username)
            LIMIT ?""",
        (pattern, pattern, pattern, query, f"{query}%", limit),
    ).fetchall()
    groups[1]["items"] = [
        {"title": row["username"], "subtitle": row["tagline"] or "Robotics community member",
         "url": url_for("profile", username=row["username"])}
        for row in people
    ]

    teams = conn.execute(
        """SELECT program,number,name,region
             FROM teams
            WHERE lower(name) LIKE lower(?) OR CAST(number AS TEXT) LIKE ?
               OR lower(region) LIKE lower(?)
            ORDER BY CASE WHEN CAST(number AS TEXT)=? THEN 0
                          WHEN lower(name)=lower(?) THEN 0
                          WHEN lower(name) LIKE lower(?) THEN 1 ELSE 2 END,
                     number
            LIMIT ?""",
        (pattern, pattern, pattern, query, query, f"{query}%", limit),
    ).fetchall()
    groups[2]["items"] = [
        {"title": f"Team {row['number']} - {row['name']}",
         "subtitle": row["region"] or f"{TEAM_PROGRAMS[row['program']]} team",
         "url": url_for("team_detail", program=row["program"], number=row["number"])}
        for row in teams
    ]
    # Fill the rest of the team results from the real FTC registry, so any team
    # can be found from the search box — not just the ones with a Botfolio
    # account. Best-effort: if the registry is unreachable we simply show fewer.
    if len(query) >= 2 and len(groups[2]["items"]) < limit:
        # An FRC team may share its number with an FTC team, so only FTC rows
        # should suppress a result from the FTC registry.
        claimed_numbers = {
            row["number"] for row in teams if row["program"] == "ftc"
        }
        try:
            # A tight timeout keeps the typeahead responsive; a slow/unreachable
            # registry just yields fewer results rather than stalling the box.
            matches = ftc_teams.search(query, limit=limit, timeout=REGISTRY_SEARCH_TIMEOUT)
            # Only spend a second request when the exact number isn't already in
            # the name-search results (short numbers like "254" match "254xx").
            if query.isdigit() and all(m["number"] != int(query) for m in matches):
                exact = ftc_teams.lookup(int(query), timeout=REGISTRY_SEARCH_TIMEOUT)
                if exact:
                    matches = [exact, *matches]
            for match in matches:
                if len(groups[2]["items"]) >= limit:
                    break
                if match["number"] in claimed_numbers:
                    continue
                groups[2]["items"].append({
                    "title": f"Team {match['number']} - {match['name']}",
                    "subtitle": match["location"] or "FTC team",
                    "badge": "Not on Botfolio",
                    "url": url_for(
                        "team_detail", program="ftc", number=match["number"]
                    ),
                })
        except ftc_teams.FtcApiError:
            pass

    tags = conn.execute(
        """SELECT t.name,COUNT(DISTINCT d.id) uses
             FROM tags t
             LEFT JOIN design_tags dt ON dt.tag_id=t.id
             LEFT JOIN designs d ON d.id=dt.design_id AND d.is_hidden=0
            WHERE lower(t.name) LIKE lower(?)
            GROUP BY t.id,t.name
            ORDER BY CASE WHEN lower(t.name)=lower(?) THEN 0
                          WHEN lower(t.name) LIKE lower(?) THEN 1 ELSE 2 END,
                     uses DESC,t.name
            LIMIT ?""",
        (pattern, query, f"{query}%", limit),
    ).fetchall()
    groups[3]["items"] = [
        {"title": display_tag(row["name"]),
         "subtitle": f"{row['uses']} design{'s' if row['uses'] != 1 else ''}",
         "url": url_for("gallery", q=row["name"])}
        for row in tags
    ]

    lowered = query.casefold()
    for title, endpoint, keywords in SITE_SEARCH_PAGES:
        if lowered in f"{title} {keywords}".casefold():
            groups[4]["items"].append(
                {"title": title, "subtitle": "Botfolio page", "url": url_for(endpoint)}
            )
            if len(groups[4]["items"]) >= limit:
                break
    if len(groups[4]["items"]) < limit:
        from academy.catalog import CATALOG, PATHWAYS
        for platform, courses in CATALOG.items():
            for course in courses:
                if course["status"] != "Live":
                    continue
                searchable = " ".join((course["title"], course["summary"], course["outcome"],
                                       PATHWAYS[platform]["name"], *course["skills"]))
                if lowered not in searchable.casefold():
                    continue
                groups[4]["items"].append({
                    "title": course["title"],
                    "subtitle": f"{PATHWAYS[platform]['name']} CAD Academy course",
                    "url": url_for("learn_course", platform=platform,
                                   course_slug=course["slug"]),
                })
                if len(groups[4]["items"]) >= limit:
                    break
            if len(groups[4]["items"]) >= limit:
                break
    return groups


@app.route("/search")
def site_search():
    query = (request.args.get("q") or "").strip()[:100]
    groups = site_search_results(db.get_db(), query, limit=24)
    total = sum(len(group["items"]) for group in groups)
    return render_template("search.html", q=query, search_groups=groups, total=total)


@app.route("/api/search")
@ratelimit.limit("global-search", 90, 60)
def global_search_api():
    query = (request.args.get("q") or "").strip()[:100]
    if len(query) < 2:
        return jsonify(query=query, groups=[], total=0)
    groups = site_search_results(db.get_db(), query)
    # The design rows are dropped rather than serialized: each is a whole
    # `SELECT d.*` row, so it carries cad_link and onshape_link, and this
    # endpoint answers anyone. That published, unauthenticated, exactly the CAD
    # URLs /designs/<id>/cad now asks for an account before handing over. The
    # typeahead reads only url, title, badge and subtitle; the design row is
    # there for the server-rendered search page, which builds its own groups.
    groups = [{**group, "items": [{key: value for key, value in item.items()
                                   if key != "design"} for item in group["items"]]}
              for group in groups]
    return jsonify(query=query, groups=groups,
                   total=sum(len(group["items"]) for group in groups))


# --------------------------------------------------------------------------
# Admin team credit
# --------------------------------------------------------------------------
# An admin uploading on behalf of a team identifies it by number. The name is
# only a label, so it is resolved rather than typed -- see the picker in
# templates/_team_credit.html, which resolves it live, and this helper, which
# resolves it again on the server so the credit is still correct when the form
# is posted with JavaScript off.


def credit_team_name(conn, number, confirmed_name="", program="ftc"):
    """The name to file an admin's team credit under.

    `confirmed_name` is what the picker resolved for this exact number; the
    picker clears it the moment the number changes, so it is never a stale label
    from a different team. Everything after it is the fallback chain for a form
    posted without JavaScript: Botfolio's own row first (a claimed team may have
    corrected its name), then the official FTC registry, and finally the number
    itself, so a registry outage still credits the right team.
    """
    confirmed = (confirmed_name or "").strip()
    if confirmed:
        return confirmed[:100]
    if not number:
        return ""
    program = _team_program(program) or "ftc"
    row = conn.execute(
        "SELECT name FROM teams WHERE program=? AND number=?", (program, number)
    ).fetchone()
    if row and (row["name"] or "").strip():
        return row["name"].strip()[:100]
    try:
        team = _team_registry(program).lookup(number, timeout=REGISTRY_SEARCH_TIMEOUT)
    except (ftc_teams.FtcApiError, frc_teams.FrcApiError):
        team = None
    return (team["name"][:100] if team else f"Team {number}")


def _credit_result(number, name, on_botfolio, location="", source="registry"):
    return {"number": number, "name": name, "location": location,
            "on_botfolio": on_botfolio, "source": source}


def _botfolio_credit_rows(conn, numbers, program="ftc"):
    """Botfolio's own rows for these team numbers, keyed by number.

    Reference profiles count: they were created by an earlier admin credit, and
    reusing their row is what keeps a team's designs together under one profile.
    """
    if not numbers:
        return {}
    placeholders = ",".join("?" * len(numbers))
    return {row["number"]: row for row in conn.execute(
        f"SELECT number,name,profile_status FROM teams WHERE program=? "
        f"AND number IN ({placeholders})",
        [program, *numbers]).fetchall()}


@app.route("/api/admin/team-credit")
@admin_required
@ratelimit.limit("admin-team-credit", 120, 60, methods=None)
def admin_team_credit_api():
    """Resolve a team for the admin credit control, by number or by name.

    Both halves answer the same shape so the picker has one rendering path.
    `state` distinguishes a confirmed "no such team" from "the registry did not
    answer", because telling an admin a real team does not exist is worse than
    telling them to try again.
    """
    conn = db.get_db()
    program = _team_program(request.args.get("program")) or "ftc"
    registry = _team_registry(program)
    number = request.args.get("number", type=int)
    if number is not None:
        if not 1 <= number <= 999999:
            return jsonify(teams=[], state="invalid")
        row = _botfolio_credit_rows(conn, [number], program).get(number)
        if row:
            return jsonify(state="found", teams=[_credit_result(
                number, row["name"], row["profile_status"] == "claimed",
                source="botfolio")])
        try:
            team = registry.lookup(number, timeout=REGISTRY_SEARCH_TIMEOUT)
        except (ftc_teams.FtcApiError, frc_teams.FrcApiError):
            return jsonify(teams=[], state="error")
        if not team:
            return jsonify(teams=[], state="absent")
        return jsonify(state="found", teams=[_credit_result(
            team["number"], team["name"], False, team["location"])])

    query = (request.args.get("q") or "").strip()[:80]
    if len(query) < 2:
        return jsonify(teams=[], state="short")
    try:
        found = registry.search(query, limit=10, timeout=REGISTRY_SEARCH_TIMEOUT)
    except (ftc_teams.FtcApiError, frc_teams.FrcApiError):
        found, registry_failed = [], True
    else:
        registry_failed = False
    known = _botfolio_credit_rows(conn, [team["number"] for team in found], program)
    results = [_credit_result(team["number"],
                              known[team["number"]]["name"] if team["number"] in known
                              else team["name"],
                              team["number"] in known
                              and known[team["number"]]["profile_status"] == "claimed",
                              team["location"],
                              "botfolio" if team["number"] in known else "registry")
               for team in found]
    # Teams only Botfolio knows about -- reference profiles from earlier credits,
    # and anyone the registry search happened to miss -- are appended so a second
    # design lands on the same profile as the first.
    seen = {team["number"] for team in found}
    for row in conn.execute(
        "SELECT number,name,profile_status FROM teams WHERE program=? "
        "AND lower(name) LIKE lower(?) ORDER BY number LIMIT 10",
        (program, f"%{query}%")
    ).fetchall():
        if row["number"] not in seen:
            results.append(_credit_result(row["number"], row["name"],
                                          row["profile_status"] == "claimed",
                                          source="botfolio"))
    if not results and registry_failed:
        return jsonify(teams=[], state="error")
    return jsonify(teams=results[:12], state="found" if results else "absent")


# Quick attribute filters offered on the gallery as toggle "tags". Each is a
# self-contained WHERE fragment (no bound params) that ANDs with the others, so a
# visitor can ask for, say, competition-tested designs that are also downloadable.
# COALESCE + `<>` keeps every fragment portable across SQLite and Postgres.
DESIGN_TAG_FILTERS = (
    ("tested", "Competition tested", "d.competition_tested = 1"),
    ("downloadable", "Downloadable model", "COALESCE(d.model_filename, '') <> ''"),
    ("cad", "CAD available",
     "(COALESCE(d.onshape_link, '') <> '' OR COALESCE(d.cad_link, '') <> '')"),
)


@app.route("/gallery")
def gallery():
    conn = db.get_db()
    query = (request.args.get("q") or "").strip()
    program = _team_program(request.args.get("program"), default="") or ""
    season_id = request.args.get("season", type=int)
    archetype_id = request.args.get("archetype", type=int)
    design_type = (request.args.get("type") or "").strip()
    if design_type not in DESIGN_TYPES:
        design_type = ""
    chosen_functions = [key for key in request.args.getlist("function") if key in DESIGN_FUNCTIONS]
    cad_software = (request.args.get("cad") or "").strip().lower()
    if cad_software not in CAD_SOFTWARE:
        cad_software = ""

    # Keep the canonical order and drop anything unrecognised so the toggles
    # can only ever add the fragments we defined above.
    chosen_tags = set(request.args.getlist("tag"))
    selected_tags = [key for key, _, _ in DESIGN_TAG_FILTERS if key in chosen_tags]

    # The sort control orders designs *within* each shelf bucket:
    # DESIGN_SHELF_ORDER is applied first, so "Most liked" surfaces the
    # best-liked team designs rather than lifting an admin upload to the top.
    sort = request.args.get("sort") or "newest"
    sort_orders = {
        "newest": "d.created_at DESC, d.id DESC",
        "liked": "like_count DESC, d.created_at DESC, d.id DESC",
        "viewed": "visit_count DESC, d.created_at DESC, d.id DESC",
    }
    if sort not in sort_orders:
        sort = "newest"
    requested_page = max(request.args.get("page", default=1, type=int) or 1, 1)
    per_page = 50
    where = ["d.is_hidden = 0"]
    params = []

    if program:
        where.append("d.program = ?")
        params.append(program)

    if query:
        like = f"%{query}%"
        # A design is a search hit on its own title/description, on a tag that
        # hasn't been voted into the ground, or on the team that made it — by
        # name or by number, so "RoboKnights" and "5064" both surface that
        # team's designs. The team match is a correlated EXISTS rather than a
        # join so it drops straight into the shared COUNT query too.
        where.append(
            """(d.title LIKE ? OR d.description LIKE ? OR EXISTS (
                   SELECT 1 FROM teams tm
                    WHERE tm.id=d.team_id
                      AND (tm.name LIKE ? OR CAST(tm.number AS TEXT) LIKE ?)
               ) OR EXISTS (
                   SELECT 1 FROM design_tags dt
                   JOIN tags t ON t.id=dt.tag_id
                  WHERE dt.design_id=d.id AND t.name LIKE ?
                    AND COALESCE((SELECT SUM(tv.value) FROM tag_votes tv
                                  WHERE tv.design_id=dt.design_id
                                    AND tv.tag_id=dt.tag_id),0) > ?
               ))"""
        )
        params.extend([like, like, like, like, like, BURIED_SCORE])

    if season_id:
        where.append("d.season_id = ?")
        params.append(season_id)

    if archetype_id:
        where.append("d.archetype_id = ?")
        params.append(archetype_id)

    if design_type:
        where.append("d.design_type = ?")
        params.append(design_type)
    for function_key in chosen_functions:
        where.append("EXISTS (SELECT 1 FROM design_functions df WHERE df.design_id=d.id AND df.function_key=?)")
        params.append(function_key)

    if cad_software:
        where.append("d.cad_software = ?")
        params.append(cad_software)

    tag_clauses = {key: clause for key, _, clause in DESIGN_TAG_FILTERS}
    for key in selected_tags:
        where.append(tag_clauses[key])

    where_sql = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM designs d WHERE {where_sql}", params
    ).fetchone()["n"]
    total_pages = max(1, math.ceil(total / per_page))
    page = min(requested_page, total_pages)
    offset = (page - 1) * per_page
    designs = conn.execute(
        f"""SELECT d.*,u.username,s.name AS season_name,a.name AS archetype_name,
                    tm.number AS team_number,tm.name AS team_name,
                    tm.program AS team_program,
                    (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
                    (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count,
                    (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count
               FROM designs d
               JOIN users u ON u.id=d.user_id
               LEFT JOIN seasons s ON s.id=d.season_id
               LEFT JOIN archetypes a ON a.id=d.archetype_id
               LEFT JOIN teams tm ON tm.id=d.team_id
              WHERE {where_sql}
              ORDER BY {DESIGN_SHELF_ORDER},
                       {sort_orders[sort]}
              LIMIT ? OFFSET ?""",
        [*params, per_page, offset],
    ).fetchall()

    if total_pages <= 9:
        page_numbers = list(range(1, total_pages + 1))
    else:
        candidates = {1, total_pages, *range(max(2, page - 2), min(total_pages, page + 2) + 1)}
        page_numbers, previous = [], 0
        for number in sorted(candidates):
            if previous and number - previous > 1:
                page_numbers.append(None)
            page_numbers.append(number)
            previous = number

    if program:
        seasons = conn.execute(
            "SELECT * FROM seasons WHERE program=? ORDER BY sort_order DESC", (program,)
        ).fetchall()
    else:
        seasons = conn.execute(
            "SELECT * FROM seasons ORDER BY program,sort_order DESC"
        ).fetchall()
    if season_id:
        archetypes = conn.execute(
            "SELECT * FROM archetypes WHERE season_id = ? OR season_id IS NULL "
            "ORDER BY name",
            (season_id,),
        ).fetchall()
    else:
        if program:
            archetypes = conn.execute(
                """SELECT DISTINCT a.* FROM archetypes a
                     LEFT JOIN seasons s ON s.id=a.season_id
                    WHERE a.season_id IS NULL OR s.program=? ORDER BY a.name""",
                (program,),
            ).fetchall()
        else:
            archetypes = conn.execute("SELECT * FROM archetypes ORDER BY name").fetchall()

    return render_template(
        "gallery.html", designs=designs, seasons=seasons, archetypes=archetypes,
        q=query, season_id=season_id, archetype_id=archetype_id, sort=sort,
        cad_software=cad_software, cad_software_choices=CAD_SOFTWARE,
        program=program, programs=TEAM_PROGRAMS,
        tag_filters=DESIGN_TAG_FILTERS, tags=selected_tags,
        design_type=design_type, chosen_functions=chosen_functions,
        design_types=DESIGN_TYPES, design_functions=DESIGN_FUNCTIONS,
        page=page, total_pages=total_pages, total=total,
        page_numbers=page_numbers,
    )


@app.route("/designs/<int:design_id>")
def design_detail(design_id):
    conn = db.get_db()
    design = conn.execute(
        """
        SELECT d.*, u.username, s.name AS season_name, a.name AS archetype_name,
               tm.number AS team_number, tm.name AS team_name,
               tm.program AS team_program,
               (SELECT COUNT(*) FROM design_view_events WHERE design_id=d.id) visit_count,
               (SELECT COUNT(*) FROM design_downloads WHERE design_id=d.id) download_count,
               (SELECT COUNT(*) FROM design_downloads WHERE design_id=d.id AND kind='cad_link') link_visit_count,
               (SELECT COUNT(*) FROM design_likes WHERE design_id=d.id) like_count,
               (SELECT COUNT(*) FROM comments WHERE design_id=d.id AND status='visible') comment_count,
               EXISTS(SELECT 1 FROM design_of_week_history dwh WHERE dwh.design_id=d.id) is_design_of_week,
               EXISTS(SELECT 1 FROM design_of_week_awards dw WHERE dw.design_id=d.id AND dw.is_current=1 AND dw.current_week=?) is_current_design_of_week
          FROM designs d
          JOIN users u ON u.id = d.user_id
          LEFT JOIN seasons s ON s.id = d.season_id
          LEFT JOIN archetypes a ON a.id = d.archetype_id
          LEFT JOIN teams tm ON tm.id = d.team_id
         WHERE d.id = ?
        """,
        (design_week_start(), design_id),
    ).fetchone()
    if design is None:
        abort(404)
    if design["is_hidden"] and not (current_user() and (current_user()["is_admin"] or current_user()["id"] == design["user_id"])):
        abort(404)

    design_images = conn.execute(
        "SELECT * FROM design_images WHERE design_id=? ORDER BY position,id",
        (design_id,),
    ).fetchall()

    viewer = current_user()
    liked = bool(viewer and conn.execute("SELECT 1 FROM design_likes WHERE user_id=? AND design_id=?", (viewer["id"], design_id)).fetchone())
    all_tags = tags_for_design(design_id, viewer["id"] if viewer else None)
    visible = [t for t in all_tags if t["score"] > BURIED_SCORE]
    buried = [t for t in all_tags if t["score"] <= BURIED_SCORE]

    feedback = None
    if viewer:
        feedback = conn.execute(
            "SELECT * FROM ai_feedback WHERE design_id=? AND requester_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (design_id, viewer["id"]),
        ).fetchone()

    rubric = None
    if feedback and feedback["status"] == "ok" and feedback["rubric_json"]:
        try:
            rubric = json.loads(feedback["rubric_json"])
        except json.JSONDecodeError:
            rubric = None

    comment_rows = conn.execute(
        """SELECT c.*, u.username, u.profile_image, u.deleted_at,
                  c.created_at >= datetime('now','-15 minutes') can_edit,
                  (SELECT t.number FROM memberships m JOIN teams t ON t.id=m.team_id
                    WHERE m.user_id=u.id ORDER BY t.program,t.number LIMIT 1) team_number,
                  (SELECT t.program FROM memberships m JOIN teams t ON t.id=m.team_id
                    WHERE m.user_id=u.id ORDER BY t.program,t.number LIMIT 1) team_program,
                  (SELECT COUNT(*) FROM comment_reports cr WHERE cr.comment_id=c.id AND cr.status='open') report_count,
                  (SELECT COUNT(*) FROM comment_helpful ch WHERE ch.comment_id=c.id) helpful_count,
                  EXISTS(SELECT 1 FROM comment_helpful ch WHERE ch.comment_id=c.id AND ch.user_id=?) viewer_helpful
             FROM comments c JOIN users u ON u.id=c.user_id
            WHERE c.design_id=? ORDER BY c.created_at, c.id""",
        (viewer["id"] if viewer else -1, design_id),
    ).fetchall()
    top_comments, replies = [], {}
    for comment in comment_rows:
        if comment["parent_id"] is None:
            top_comments.append(comment)
        else:
            replies.setdefault(comment["parent_id"], []).append(comment)

    # Suggestions for the "Add a tag" box: tags other designs in this design's
    # season or model type already carry, most-used first, minus the ones this
    # design has. Falls back to the most-used tags site-wide when the design has
    # neither a season nor a model type to scope by.
    scope, scope_params = [], []
    if design["season_id"]:
        scope.append("d2.season_id = ?")
        scope_params.append(design["season_id"])
    if design["archetype_id"]:
        scope.append("d2.archetype_id = ?")
        scope_params.append(design["archetype_id"])
    # `1=1` rather than a bare `1`: this falls back to unscoped for any design
    # published without a season or a model type, and PostgreSQL rejects an
    # integer where a boolean belongs -- which took the whole page down.
    scope_sql = "(" + " OR ".join(scope) + ")" if scope else "1=1"
    suggested_rows = conn.execute(
        f"""
        SELECT t.name, COUNT(*) AS uses
          FROM design_tags dt
          JOIN designs d2 ON d2.id = dt.design_id AND d2.is_hidden = 0
          JOIN tags t ON t.id = dt.tag_id
         WHERE d2.id <> ?
           AND {scope_sql}
           AND dt.tag_id NOT IN (SELECT tag_id FROM design_tags WHERE design_id = ?)
         GROUP BY t.id
         ORDER BY uses DESC, t.name
         LIMIT 24
        """,
        (design_id, *scope_params, design_id),
    ).fetchall()
    suggested_tags = [display_tag(row["name"]) for row in suggested_rows]
    resources = conn.execute(
        "SELECT r.*,(SELECT COUNT(*) FROM resource_downloads rd WHERE rd.resource_id=r.id) download_count "
        "FROM design_resources r WHERE r.design_id=? ORDER BY r.position,r.id", (design_id,)
    ).fetchall()
    linked_subsystems = conn.execute(
        "SELECT rel.*,d.title,d.image_filename,u.username FROM design_relationships rel "
        "JOIN designs d ON d.id=rel.target_design_id JOIN users u ON u.id=d.user_id "
        "WHERE rel.source_design_id=? AND rel.relationship_type='has_subsystem' AND d.is_hidden=0 "
        "ORDER BY rel.created_at,rel.id", (design_id,)
    ).fetchall()
    bom_items = conn.execute(
        "SELECT * FROM bom_items WHERE design_id=? ORDER BY position,id", (design_id,)
    ).fetchall()
    bom_total_cents = sum(round(row["quantity"] * row["unit_cost_cents"])
                          for row in bom_items if row["unit_cost_cents"] is not None)
    is_owner = bool(viewer and (viewer["id"] == design["user_id"] or viewer["is_admin"]))

    return render_template(
        "design_detail.html", design=design, tags=visible, buried_tags=buried,
        suggested_tags=suggested_tags,
        feedback=feedback, rubric=rubric, liked=liked,
        model_viewable=model_is_viewable(
            design["model_filename"], design["model_size_bytes"]
        ),
        # Which of the two download-only reasons the page should give.
        model_is_cad_source=is_cad_source(design["model_filename"]),
        programs=TEAM_PROGRAMS,
        saved=bool(viewer and conn.execute("SELECT 1 FROM saved_designs WHERE user_id=? AND design_id=?", (viewer["id"], design_id)).fetchone()),
        contributors=conn.execute("SELECT u.username,dc.role FROM design_contributors dc JOIN users u ON u.id=dc.user_id WHERE dc.design_id=? ORDER BY dc.credited_at,u.username", (design_id,)).fetchall(),
        comments=top_comments, replies=replies, design_images=design_images,
        design_week_awards=conn.execute(
            "SELECT week_start,selected_at FROM design_of_week_history WHERE design_id=? ORDER BY week_start DESC",
            (design_id,),
        ).fetchall(),
        resources=resources, linked_subsystems=linked_subsystems,
        bom_items=bom_items, bom_total_cents=bom_total_cents,
        engineering_owner=is_owner, design_functions=DESIGN_FUNCTIONS,
        design_types=DESIGN_TYPES,
    )


@app.route("/designs/<int:design_id>/view", methods=["POST"])
@ratelimit.limit("design-view", 30, 300)
def record_design_view(design_id):
    """Record one engaged browser view, at most once per person per cooldown.

    Rendering the public HTML is intentionally side-effect free: crawlers,
    unfurlers, HEAD requests and speculative navigation can fetch it without
    changing a public metric. The page calls this endpoint only after it has
    been visibly open or the visitor has interacted with it.

    ``design_view_state`` makes the 30-minute decision atomic. Its conditional
    UPDATE lets exactly one concurrent request advance an existing visitor;
    INSERT OR IGNORE does the same for a first visit. Only that winning request
    appends the permanent event counted by the UI.
    """
    conn = db.get_db()
    design = conn.execute(
        "SELECT id FROM designs WHERE id=? AND is_hidden=0", (design_id,)
    ).fetchone()
    if design is None:
        abort(404)

    if automated_view_request():
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM design_view_events WHERE design_id=?",
            (design_id,),
        ).fetchone()["n"]
        response = jsonify(counted=False, view_count=count)
        response.headers["Cache-Control"] = "no-store"
        return response

    key = visitor_key()
    cutoff = f"-{VISIT_COOLDOWN_MINUTES} minutes"
    advanced = conn.execute(
        "UPDATE design_view_state SET last_viewed_at=datetime('now') "
        "WHERE design_id=? AND visitor_key=? "
        "AND last_viewed_at<=datetime('now', ?)",
        (design_id, key, cutoff),
    )
    counted = advanced.rowcount == 1

    if not counted:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO design_view_state"
            "(design_id,visitor_key,last_viewed_at) VALUES (?,?,datetime('now'))",
            (design_id, key),
        )
        counted = inserted.rowcount == 1

    if counted:
        conn.execute(
            "INSERT INTO design_view_events(design_id) VALUES (?)", (design_id,)
        )

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM design_view_events WHERE design_id=?",
        (design_id,),
    ).fetchone()["n"]
    conn.commit()
    response = jsonify(counted=counted, view_count=count)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/designs/<int:design_id>/like", methods=["POST"])
@login_required
def toggle_design_like(design_id):
    conn = db.get_db()
    if not conn.execute("SELECT 1 FROM designs WHERE id=? AND is_hidden=0", (design_id,)).fetchone():
        abort(404)
    user_id = current_user()["id"]
    liked = bool(conn.execute("SELECT 1 FROM design_likes WHERE user_id=? AND design_id=?", (user_id, design_id)).fetchone())
    if liked:
        conn.execute("DELETE FROM design_likes WHERE user_id=? AND design_id=?", (user_id, design_id))
        liked = False
    else:
        conn.execute("INSERT INTO design_likes (user_id, design_id) VALUES (?,?)", (user_id, design_id))
        liked = True
    conn.commit()
    if request.accept_mimetypes.best == "application/json":
        like_count = conn.execute(
            "SELECT COUNT(*) n FROM design_likes WHERE design_id=?", (design_id,)
        ).fetchone()["n"]
        return jsonify(liked=liked, like_count=like_count)
    return redirect(url_for("design_detail", design_id=design_id))


@app.route("/designs/<int:design_id>/save", methods=["POST"])
@login_required
def toggle_saved_design(design_id):
    conn = db.get_db()
    if not conn.execute("SELECT 1 FROM designs WHERE id=? AND is_hidden=0", (design_id,)).fetchone():
        abort(404)
    user_id = current_user()["id"]
    if conn.execute("SELECT 1 FROM saved_designs WHERE user_id=? AND design_id=?", (user_id, design_id)).fetchone():
        conn.execute("DELETE FROM saved_designs WHERE user_id=? AND design_id=?", (user_id, design_id))
        flash("Removed from Saved Designs.", "success")
    else:
        conn.execute("INSERT INTO saved_designs(user_id,design_id) VALUES (?,?)", (user_id, design_id))
        flash("Saved to your Robotics Profile.", "success")
    conn.commit()
    return redirect(url_for("design_detail", design_id=design_id))


@app.route("/comments/<int:comment_id>/helpful", methods=["POST"])
@login_required
def toggle_comment_helpful(comment_id):
    conn = db.get_db()
    comment = conn.execute("SELECT * FROM comments WHERE id=? AND status='visible'", (comment_id,)).fetchone()
    if not comment:
        abort(404)
    user_id = current_user()["id"]
    if comment["user_id"] == user_id:
        flash("You cannot mark your own answer as helpful.", "error")
    elif conn.execute("SELECT 1 FROM comment_helpful WHERE comment_id=? AND user_id=?", (comment_id, user_id)).fetchone():
        conn.execute("DELETE FROM comment_helpful WHERE comment_id=? AND user_id=?", (comment_id, user_id))
    else:
        conn.execute("INSERT INTO comment_helpful(comment_id,user_id) VALUES (?,?)", (comment_id, user_id))
    conn.commit()
    return redirect(url_for("design_detail", design_id=comment["design_id"]) + f"#comment-{comment_id}")


@app.route("/designs/<int:design_id>/design-of-the-week", methods=["POST"])
@admin_required
def select_design_of_week(design_id):
    conn = db.get_db()
    if not conn.execute("SELECT 1 FROM designs WHERE id=? AND is_hidden=0", (design_id,)).fetchone():
        abort(404)
    week_start = design_week_start()
    current = conn.execute(
        "SELECT is_current,current_week FROM design_of_week_awards WHERE design_id=?",
        (design_id,),
    ).fetchone()
    removing = bool(current and current["is_current"] and current["current_week"] == week_start)
    if removing:
        # Withdrawn inside the same week it was granted, so the award never
        # stands: this week's dated history row goes with the selection, and the
        # badge on the design page goes with it. The awards row is deleted
        # rather than flagged is_current=0 because the legacy backfill in
        # ensure_runtime_schema() re-derives a history row from any surviving
        # awards row's selected_at, which would put the badge back on restart.
        # Earlier, completed weeks keep their own history rows untouched.
        conn.execute(
            "DELETE FROM design_of_week_history WHERE design_id=? AND week_start=?",
            (design_id, week_start),
        )
        conn.execute("DELETE FROM design_of_week_awards WHERE design_id=?", (design_id,))
    else:
        conn.execute(
            "INSERT INTO design_of_week_awards(design_id,selected_by,selected_at,is_current,current_week) VALUES (?,?,datetime('now'),1,?) "
            "ON CONFLICT(design_id) DO UPDATE SET selected_by=excluded.selected_by,selected_at=excluded.selected_at,is_current=1,current_week=excluded.current_week",
            (design_id, current_user()["id"], week_start),
        )
        conn.execute(
            "INSERT INTO design_of_week_history(design_id,week_start,selected_by) VALUES (?,?,?) "
            "ON CONFLICT(design_id,week_start) DO NOTHING",
            (design_id, week_start, current_user()["id"]),
        )
    conn.commit()
    flash("Removed from this week's Designs of the Week. This week's award no longer stands." if removing
          else "Added to this week's Designs of the Week.", "success")
    return redirect(url_for("design_detail", design_id=design_id))


@app.route("/designs/<int:design_id>/comments", methods=["POST"])
@ratelimit.limit("comment", 12, 600)
@login_required
@verified_required
def add_comment(design_id):
    conn = db.get_db()
    design = conn.execute("SELECT id,user_id FROM designs WHERE id=? AND is_hidden=0", (design_id,)).fetchone()
    if design is None:
        abort(404)
    body = (request.form.get("body") or "").strip()
    if not 1 <= len(body) <= 2000:
        flash("Comments must be between 1 and 2,000 characters.", "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#comments")
    try:
        moderate_public_content(texts=[body], use_api=not app.testing)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#comments")
    parent_id = request.form.get("parent_id", type=int)
    parent = None
    if parent_id:
        parent = conn.execute("SELECT * FROM comments WHERE id=? AND design_id=?", (parent_id, design_id)).fetchone()
        if parent is None or parent["parent_id"] is not None:
            abort(400)
    cursor = conn.execute(
        "INSERT INTO comments(design_id,user_id,parent_id,body) VALUES (?,?,?,?)",
        (design_id, current_user()["id"], parent_id, body),
    )
    target_id = parent["user_id"] if parent else design["user_id"]
    if target_id != current_user()["id"]:
        conn.execute(
            "INSERT INTO notifications(user_id,actor_id,design_id,comment_id,kind) VALUES (?,?,?,?,?)",
            (target_id, current_user()["id"], design_id, cursor.lastrowid, "reply" if parent else "comment"),
        )
    conn.commit()
    flash("Reply posted." if parent else "Comment posted.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#comment-" + str(cursor.lastrowid))


def get_comment_or_404(comment_id):
    comment = db.get_db().execute(
        "SELECT c.*,d.user_id design_owner_id FROM comments c JOIN designs d ON d.id=c.design_id WHERE c.id=?",
        (comment_id,),
    ).fetchone()
    if comment is None:
        abort(404)
    return comment


@app.route("/comments/<int:comment_id>/edit", methods=["POST"])
@login_required
def edit_comment(comment_id):
    comment = get_comment_or_404(comment_id)
    user = current_user()
    within_window = db.get_db().execute(
        "SELECT created_at >= datetime('now','-15 minutes') ok FROM comments WHERE id=?", (comment_id,)
    ).fetchone()["ok"]
    if not user["is_admin"] and (comment["user_id"] != user["id"] or not within_window):
        abort(403)
    body = (request.form.get("body") or "").strip()
    if not 1 <= len(body) <= 2000:
        flash("Comments must be between 1 and 2,000 characters.", "error")
    else:
        try:
            moderate_public_content(texts=[body], use_api=not app.testing)
            db.get_db().execute("UPDATE comments SET body=?,updated_at=datetime('now') WHERE id=?", (body, comment_id))
            db.get_db().commit()
            flash("Comment updated.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
    return redirect(url_for("design_detail", design_id=comment["design_id"]) + f"#comment-{comment_id}")


@app.route("/comments/<int:comment_id>/delete", methods=["POST"])
@login_required
def delete_comment(comment_id):
    comment = get_comment_or_404(comment_id)
    user = current_user()
    if not (user["is_admin"] or comment["user_id"] == user["id"] or comment["design_owner_id"] == user["id"]):
        abort(403)
    db.get_db().execute("UPDATE comments SET status='deleted',body='[deleted]',updated_at=datetime('now') WHERE id=?", (comment_id,))
    db.get_db().commit()
    flash("Comment removed.", "success")
    return redirect(url_for("design_detail", design_id=comment["design_id"]) + "#comments")


@app.route("/comments/<int:comment_id>/visibility", methods=["POST"])
@login_required
def toggle_comment_visibility(comment_id):
    comment = get_comment_or_404(comment_id)
    user = current_user()
    if not (user["is_admin"] or comment["design_owner_id"] == user["id"]):
        abort(403)
    if comment["status"] == "deleted":
        abort(400)
    new_status = "visible" if comment["status"] == "hidden" else "hidden"
    db.get_db().execute("UPDATE comments SET status=?,updated_at=datetime('now') WHERE id=?", (new_status, comment_id))
    db.get_db().commit()
    flash("Comment restored." if new_status == "visible" else "Comment hidden.", "success")
    return redirect(url_for("design_detail", design_id=comment["design_id"]) + "#comments")


@app.route("/comments/<int:comment_id>/report", methods=["POST"])
@login_required
def report_comment(comment_id):
    comment = get_comment_or_404(comment_id)
    reason = (request.form.get("reason") or "Needs moderator review").strip()[:500]
    db.get_db().execute(
        "INSERT OR IGNORE INTO comment_reports(comment_id,reporter_id,reason) VALUES (?,?,?)",
        (comment_id, current_user()["id"], reason),
    )
    db.get_db().commit()
    flash("Thanks. A moderator can now review this comment.", "success")
    return redirect(url_for("design_detail", design_id=comment["design_id"]) + f"#comment-{comment_id}")


@app.route("/notifications")
@login_required
def notifications():
    conn = db.get_db()
    rows = conn.execute(
        """SELECT n.*,u.username actor_name,d.title design_title
             FROM notifications n LEFT JOIN users u ON u.id=n.actor_id
             LEFT JOIN designs d ON d.id=n.design_id
            WHERE n.user_id=? ORDER BY n.created_at DESC LIMIT 100""",
        (current_user()["id"],),
    ).fetchall()
    membership_notifications = conn.execute(
        """SELECT r.*,t.program team_program,t.number team_number,t.name team_name,u.username member_name,
                  initiator.username initiator_name
             FROM team_membership_requests r JOIN teams t ON t.id=r.team_id
             JOIN users u ON u.id=r.user_id
             JOIN users initiator ON initiator.id=r.initiated_by_id
            WHERE r.status='pending' AND
                  ((r.kind='invitation' AND r.user_id=?) OR
                   (r.kind='request' AND t.owner_id=?))
            ORDER BY r.created_at DESC,r.id DESC""",
        (current_user()["id"], current_user()["id"]),
    ).fetchall()
    return render_template(
        "notifications.html", notifications=rows,
        membership_notifications=membership_notifications,
        has_unread_activity=any(row["read_at"] is None for row in rows),
    )


@app.route("/notifications/read", methods=["POST"])
@login_required
def read_notifications():
    db.get_db().execute("UPDATE notifications SET read_at=datetime('now') WHERE user_id=? AND read_at IS NULL", (current_user()["id"],))
    db.get_db().commit()
    return redirect(url_for("notifications"))


INCIDENT_TEXT_FIELDS = (
    "discovered_by", "systems_affected", "information_affected", "actions_taken",
    "credentials_rotated", "vendors_contacted", "notifications", "root_cause",
    "corrective_action",
)


def _incident_form_values():
    values = {name: request.form.get(name, "").strip() for name in INCIDENT_TEXT_FIELDS}
    values["incident_number"] = request.form.get("incident_number", "").strip().upper()
    values["discovery_date"] = request.form.get("discovery_date", "").strip()
    values["resolution_date"] = request.form.get("resolution_date", "").strip() or None
    if not values["incident_number"] or any(not values[name] for name in INCIDENT_TEXT_FIELDS):
        return None, "Complete every incident field; use ‘None’ when an item does not apply."
    for name in ("discovery_date", "resolution_date"):
        if values[name]:
            try:
                datetime.strptime(values[name], "%Y-%m-%d")
            except ValueError:
                return None, "Use a valid date in YYYY-MM-DD format."
    if values["resolution_date"] and values["resolution_date"] < values["discovery_date"]:
        return None, "Resolution date cannot be before discovery date."
    return values, None


@app.route("/admin/incidents", methods=["GET", "POST"])
@admin_required
def security_incidents():
    user = current_user()
    conn = db.connect()
    if request.method == "POST":
        values, error = _incident_form_values()
        if error:
            conn.close()
            flash(error, "error")
            return redirect(url_for("security_incidents"))
        try:
            conn.execute(
                """INSERT INTO security_incidents
                   (incident_number,discovery_date,discovered_by,systems_affected,
                    information_affected,actions_taken,credentials_rotated,vendors_contacted,
                    notifications,root_cause,corrective_action,resolution_date,created_by,updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(values[name] for name in ("incident_number", "discovery_date") + INCIDENT_TEXT_FIELDS)
                + (values["resolution_date"], user["id"], user["id"]),
            )
            conn.commit()
        except db.sqlite3.IntegrityError:
            conn.close()
            flash("That incident number already exists.", "error")
            return redirect(url_for("security_incidents"))
        conn.close()
        flash("Incident recorded.", "success")
        return redirect(url_for("security_incidents"))
    incidents = conn.execute(
        """SELECT si.*, creator.username created_by_name, editor.username updated_by_name
             FROM security_incidents si
             JOIN users creator ON creator.id=si.created_by
             JOIN users editor ON editor.id=si.updated_by
            ORDER BY (si.resolution_date IS NULL) DESC,si.discovery_date DESC,si.id DESC"""
    ).fetchall()
    conn.close()
    return render_template("security_incidents.html", incidents=incidents)


@app.route("/admin/stats")
@admin_required
def admin_stats():
    """Live growth counters: new user accounts and new (claimed) team accounts.

    Everything is a COUNT over created_at windows, so the numbers refresh on
    every load with no bookkeeping. Team accounts are the claimed profiles;
    the 'reference' rows are admin-made placeholders, not real sign-ups.
    """
    conn = db.connect()
    stats = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL) AS users_total,
          (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND created_at >= datetime('now','-1 days')) AS users_1d,
          (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND created_at >= datetime('now','-7 days')) AS users_7d,
          (SELECT COUNT(*) FROM users WHERE deleted_at IS NULL AND created_at >= datetime('now','-30 days')) AS users_30d,
          (SELECT COUNT(*) FROM teams WHERE profile_status='claimed') AS teams_total,
          (SELECT COUNT(*) FROM teams WHERE profile_status='claimed' AND created_at >= datetime('now','-1 days')) AS teams_1d,
          (SELECT COUNT(*) FROM teams WHERE profile_status='claimed' AND created_at >= datetime('now','-7 days')) AS teams_7d,
          (SELECT COUNT(*) FROM teams WHERE profile_status='claimed' AND created_at >= datetime('now','-30 days')) AS teams_30d
        """
    ).fetchone()
    conn.close()
    return render_template("admin_stats.html", stats=stats)


# --------------------------------------------------------------------------
# Finding an account
# --------------------------------------------------------------------------

# Gmail ignores the dots in the part before the @, discards anything after a
# "+", and answers to googlemail.com as well. One inbox therefore has many
# spellings, and this table stores whichever one was typed on the day.
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
ACCOUNT_SEARCH_LIMIT = 50


def canonical_inbox(address):
    """Reduce an address to the mailbox it actually reaches."""
    local, at_sign, domain = (address or "").strip().lower().partition("@")
    if not at_sign:
        return ""
    if domain in GMAIL_DOMAINS:
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def account_state(row):
    """The one phrase that explains why an account may be behaving oddly."""
    if row["deleted_at"]:
        return "deleted"
    if row["banned_at"]:
        return "banned"
    if row["suspended_at"]:
        return "suspended"
    if not row["email_verified_at"]:
        return "email never verified"
    if not row["onboarding_complete"]:
        return "onboarding unfinished"
    return "active"


def account_warnings(row):
    """Things about a stored address that no amount of correct typing fixes."""
    email = row["email"] or ""
    notes = []
    if email != email.strip():
        notes.append("stored with surrounding whitespace")
    if any(ord(character) > 127 for character in email):
        notes.append("holds characters that only look like plain letters")
    return notes


def in_order_pattern(text):
    """A LIKE pattern meaning "contains these characters, in this order".

    "friend@gmail.com" and "F.r.i.end+ftc@googlemail.com" are one inbox and
    share no useful substring, so no `LIKE '%friend%'` will ever pair them.
    Both do spell the mailbox out in order, which narrows the table to a few
    rows that canonical_inbox() then confirms exactly. Deliberately coarse:
    everything it returns is checked again below before being shown.
    """
    letters = [character for character in text if character.isalnum()]
    return "%" + "%".join(letters) + "%" if letters else ""


def find_accounts(conn, raw_query, limit=None, *, all_matches=False):
    """Every account that could plausibly be the one being looked for.

    The People section of site search hides suspended, banned and deleted
    accounts and never looks at an email address, which makes it useless for
    the case this exists to serve: somebody locked out of an account the site
    insists already exists. This looks at all of them, and says why each one
    came back so a near-miss cannot be mistaken for the real thing.
    """
    query = (raw_query or "").strip()[:254]
    if not query:
        return []
    folded = query.lower()
    pattern = f"%{folded}%"
    wanted = canonical_inbox(query)
    net = in_order_pattern(wanted.partition("@")[0]) or pattern
    rows = conn.execute(
        """SELECT id,username,email,display_name,created_at,email_verified_at,
                  suspended_at,banned_at,deleted_at,onboarding_complete,is_admin
             FROM users
            WHERE lower(username) LIKE lower(?) OR lower(email) LIKE lower(?)
               OR lower(display_name) LIKE lower(?) OR lower(email) LIKE lower(?)
            ORDER BY CASE WHEN lower(username)=lower(?) OR lower(email)=lower(?) THEN 0
                          WHEN lower(username) LIKE lower(?) THEN 1 ELSE 2 END,
                     lower(username)
            """ + ("" if all_matches else "LIMIT ?"),
        (pattern, pattern, pattern, net, query, query, f"{folded}%")
        + (() if all_matches else (limit or ACCOUNT_SEARCH_LIMIT,)),
    ).fetchall()
    accounts = []
    for row in rows:
        stored_name = (row["username"] or "").strip().lower()
        stored_email = (row["email"] or "").strip().lower()
        if folded in (stored_name, stored_email):
            reason = "exact match, apart from capitals"
        elif wanted and canonical_inbox(row["email"]) == wanted:
            reason = "the same inbox, written differently"
        elif folded in stored_name or folded in (row["display_name"] or "").lower():
            reason = "name contains what you typed"
        elif folded in stored_email:
            reason = "email contains what you typed"
        else:
            continue  # Only the in-order net matched, and it over-matches.
        accounts.append({
            "user": row,
            "state": account_state(row),
            "why": [reason, *account_warnings(row)],
        })
    return accounts


@app.route("/admin/users")
@admin_required
def admin_user_search():
    """Look an account up by name or address, however it is stored."""
    query = (request.args.get("q") or "").strip()[:100]
    return render_template(
        "admin_users.html",
        q=query,
        accounts=find_accounts(db.get_db(), query),
        limit=ACCOUNT_SEARCH_LIMIT,
    )


@app.route("/admin/incidents/<int:incident_id>", methods=["POST"])
@admin_required
def update_security_incident(incident_id):
    values, error = _incident_form_values()
    if error:
        flash(error, "error")
        return redirect(url_for("security_incidents") + f"#incident-{incident_id}")
    user = current_user()
    conn = db.connect()
    try:
        cursor = conn.execute(
            """UPDATE security_incidents SET incident_number=?,discovery_date=?,discovered_by=?,
                   systems_affected=?,information_affected=?,actions_taken=?,credentials_rotated=?,
                   vendors_contacted=?,notifications=?,root_cause=?,corrective_action=?,resolution_date=?,
                   updated_by=?,updated_at=datetime('now') WHERE id=?""",
            tuple(values[name] for name in ("incident_number", "discovery_date") + INCIDENT_TEXT_FIELDS)
            + (values["resolution_date"], user["id"], incident_id),
        )
        conn.commit()
    except db.sqlite3.IntegrityError:
        conn.close()
        flash("That incident number already exists.", "error")
        return redirect(url_for("security_incidents") + f"#incident-{incident_id}")
    conn.close()
    if not cursor.rowcount:
        abort(404)
    flash("Incident updated.", "success")
    return redirect(url_for("security_incidents") + f"#incident-{incident_id}")


@app.route("/moderation/comments")
@admin_required
def comment_moderation():
    user_query = (request.args.get("user") or "").strip()[:254]
    show_all_users = request.args.get("accounts") == "all"
    if user_query:
        # Apply the display limit after matching equivalent inbox spellings.
        user_results = find_accounts(db.get_db(), user_query, all_matches=True)
    else:
        rows = db.get_db().execute(
            """SELECT id,username,email,display_name,created_at,email_verified_at,
                      suspended_at,banned_at,deleted_at,onboarding_complete,is_admin
                 FROM users ORDER BY lower(username),id"""
            + ("" if show_all_users else " LIMIT 21")
        ).fetchall()
        user_results = [{"user": row, "state": account_state(row),
                         "why": account_warnings(row)} for row in rows]
    has_more_users = not show_all_users and len(user_results) > 20
    if not show_all_users:
        user_results = user_results[:20]
    reports = db.get_db().execute(
        """SELECT cr.*,c.body,c.status comment_status,c.design_id,
                  reporter.username reporter_name,author.username author_name,d.title design_title
             FROM comment_reports cr JOIN comments c ON c.id=cr.comment_id
             JOIN users reporter ON reporter.id=cr.reporter_id
             JOIN users author ON author.id=c.user_id JOIN designs d ON d.id=c.design_id
            WHERE cr.status='open' ORDER BY cr.created_at"""
    ).fetchall()
    content_reports = db.get_db().execute(
        """SELECT cr.*,u.username assigned_admin_name
             FROM content_reports cr LEFT JOIN users u ON u.id=cr.assigned_admin_id
            WHERE cr.workflow_status!='closed' ORDER BY cr.priority DESC,cr.created_at"""
    ).fetchall()
    hidden_designs = db.get_db().execute(
        """SELECT d.id,d.title,d.description,d.image_filename,d.updated_at,
                  owner.username owner_name,
                  (SELECT ma.reason FROM moderation_actions ma
                    WHERE ma.target_type='design' AND ma.target_id=CAST(d.id AS TEXT)
                      AND ma.action='hide'
                    ORDER BY ma.created_at DESC,ma.id DESC LIMIT 1) hide_reason
             FROM designs d JOIN users owner ON owner.id=d.user_id
            WHERE d.is_hidden=1
            ORDER BY d.updated_at DESC,d.id DESC"""
    ).fetchall()
    return render_template(
        "comment_moderation.html", reports=reports,
        content_reports=content_reports, user_query=user_query,
        user_results=user_results, hidden_designs=hidden_designs,
        show_all_users=show_all_users, has_more_users=has_more_users,
        report_reasons=REPORT_REASONS,
    )


@app.route("/moderation/content-reports/<int:report_id>", methods=["POST"])
@admin_required
def resolve_content_report(report_id):
    action = request.form.get("action")
    workflow_status = request.form.get("workflow_status")
    if action not in {"set_status", "hide_content"}:
        abort(400)
    if action == "set_status" and workflow_status not in {"new", "under_review", "action_taken", "closed"}:
        abort(400)
    conn = db.get_db()
    report = conn.execute("SELECT * FROM content_reports WHERE id=?", (report_id,)).fetchone()
    if report is None:
        abort(404)
    note = (request.form.get("note") or "").strip()[:500]
    if action == "hide_content":
        if not report["content_id"] or not str(report["content_id"]).isdigit():
            abort(400, "This report does not identify a hideable content record.")
        target_id = int(report["content_id"])
        if report["content_type"] == "design":
            conn.execute("UPDATE designs SET is_hidden=1,updated_at=datetime('now') WHERE id=?", (target_id,))
        elif report["content_type"] == "comment":
            conn.execute("UPDATE comments SET status='hidden',updated_at=datetime('now') WHERE id=? AND status!='deleted'", (target_id,))
        elif report["content_type"] == "profile":
            conn.execute("UPDATE users SET profile_image=NULL WHERE id=?", (target_id,))
        elif report["content_type"] == "team":
            conn.execute("UPDATE teams SET profile_image=NULL,banner_image=NULL WHERE id=?", (target_id,))
        else:
            abort(400, "That content type cannot be hidden from this report.")
        note = note or "Reported content hidden pending review."
        conn.execute(
            """UPDATE content_reports SET status='resolved',workflow_status='action_taken',
                      assigned_admin_id=?,decision_reason=?,
                      action_taken_at=COALESCE(action_taken_at,datetime('now'))
                 WHERE id=?""",
            (current_user()["id"], note, report_id),
        )
        audit_action = "hide_content"
    else:
        legacy_status = "resolved" if workflow_status in {"action_taken", "closed"} else "open"
        conn.execute(
            """UPDATE content_reports SET status=?,workflow_status=?,assigned_admin_id=?,
                      decision_reason=?,
                      action_taken_at=CASE WHEN ?='action_taken'
                                           THEN COALESCE(action_taken_at,datetime('now'))
                                           ELSE action_taken_at END,
                      resolved_at=CASE WHEN ?='closed' THEN datetime('now') ELSE NULL END
                 WHERE id=?""",
            (legacy_status, workflow_status, current_user()["id"], note,
             workflow_status, workflow_status, report_id),
        )
        audit_action = workflow_status
    conn.execute("INSERT INTO moderation_actions(admin_id,target_type,target_id,action,reason) VALUES (?,?,?,?,?)",
                 (current_user()["id"], "content_report", str(report_id), audit_action,
                  note or report["reason"]))
    conn.commit()
    flash("Content report updated.", "success")
    return redirect(url_for("comment_moderation"))


@app.route("/moderation/reports/<int:report_id>", methods=["POST"])
@admin_required
def resolve_comment_report(report_id):
    action = request.form.get("action")
    if action not in {"hide", "dismiss"}:
        abort(400)
    conn = db.get_db()
    report = conn.execute("SELECT * FROM comment_reports WHERE id=?", (report_id,)).fetchone()
    if report is None:
        abort(404)
    if action == "hide":
        conn.execute("UPDATE comments SET status='hidden',updated_at=datetime('now') WHERE id=? AND status!='deleted'", (report["comment_id"],))
    conn.execute("UPDATE comment_reports SET status=?,resolved_at=datetime('now') WHERE id=?", ("resolved" if action == "hide" else "dismissed", report_id))
    conn.commit()
    flash("Report resolved." if action == "hide" else "Report dismissed.", "success")
    return redirect(url_for("comment_moderation"))


# Count one download per person per cooldown, then serve the stored model.
@app.route("/designs/<int:design_id>/download")
@login_required(message="Sign in to download this design.")
# methods=None because downloads are GETs — the default POST-only filter would
# make this decorator do nothing. Models are up to 2.5 GB, so this is the
# bandwidth cap. Below @login_required, so a signed-out visitor is bounced to
# the sign-in page without spending anyone's allowance.
@ratelimit.limit("download", 30, 300, methods=None)
def download_design(design_id):
    conn = db.get_db()
    design = conn.execute("SELECT model_filename,is_hidden,user_id FROM designs WHERE id=?", (design_id,)).fetchone()
    if design is None or not design["model_filename"]:
        abort(404)
    if design["is_hidden"] and not (current_user()["is_admin"] or current_user()["id"] == design["user_id"]):
        abort(404)
    refusal = daily_budget_refusal(conn, design_id, design["user_id"])
    if refusal:
        flash(refusal, "error")
        return redirect(url_for("design_detail", design_id=design_id))
    # On S3 this redirects to a signed URL instead of streaming a multi-GB file
    # through the app and holding a worker for the whole download. Built before
    # anything is counted, so a model whose file went missing raises here and
    # leaves no row behind.
    response = infra_storage.send("models", design["model_filename"], as_attachment=True)
    record_design_download(conn, design_id, "file", response)
    return response


# Opening the CAD where it lives is the same act as downloading the file — it is
# how you get this design — so it goes through the same door: an account, the
# same daily allowance, and the same one-row-per-person record.
@app.route("/designs/<int:design_id>/cad")
@login_required(message="Sign in to open this design in CAD.")
# Cheap to serve, but it hands out a link the page no longer shows, so it gets a
# ceiling of its own on top of the daily allowance.
@ratelimit.limit("cad-link", 60, 300, methods=None)
def open_cad(design_id):
    """Send someone to where this design's CAD actually lives.

    The link used to sit in the page as a plain href, which meant the one thing
    people most want was the one thing that asked nothing of them and left no
    trace. Routing it through here is what lets the sign-in gate and the daily
    allowance cover link-only designs too, instead of only the ones that happen
    to carry an uploaded file.
    """
    conn = db.get_db()
    design = conn.execute("SELECT cad_link,onshape_link,is_hidden,user_id FROM designs WHERE id=?", (design_id,)).fetchone()
    if design is None:
        abort(404)
    if design["is_hidden"] and not (current_user()["is_admin"] or current_user()["id"] == design["user_id"]):
        abort(404)
    link = safe_cad_target(design["cad_link"] or design["onshape_link"])
    if link is None:
        abort(404)
    refusal = daily_budget_refusal(conn, design_id, design["user_id"])
    if refusal:
        flash(refusal, "error")
        return redirect(url_for("design_detail", design_id=design_id))
    response = redirect(link)
    record_design_download(conn, design_id, "cad_link", response)
    return response


def daily_budget_refusal(conn, design_id, owner_id):
    """Why this person cannot take this design's CAD right now, or None.

    Repeats are free: taking a design again while its row is still inside the
    cooldown writes nothing, so it can never cost a second slot and must never
    be refused — otherwise the allowance would punish people for a browser that
    retried. Anything else is a design they have not taken today and has to fit
    in the budget. Admins are exempt because moderating reported uploads means
    opening them, and so is the person who uploaded it, who should never be
    locked out of their own work.
    """
    viewer = current_user()
    if viewer["is_admin"] or viewer["id"] == owner_id:
        return None
    downloader_key = visitor_key()
    if recent_download_row(conn, design_id, downloader_key):
        return None
    # Their own uploads are joined out rather than merely skipped above: those
    # downloads are still recorded, and counting them would let someone burn the
    # whole allowance fetching back files they wrote themselves.
    taken = conn.execute(
        "SELECT COUNT(*) n, MIN(taken.downloaded_at) oldest FROM design_downloads taken "
        "JOIN designs ON designs.id = taken.design_id "
        "WHERE taken.visitor_key=? AND taken.downloaded_at >= datetime('now', ?) "
        "AND designs.user_id != ?",
        (downloader_key, f"-{DOWNLOAD_COOLDOWN_MINUTES} minutes", viewer["id"]),
    ).fetchone()
    if taken["n"] < DAILY_DOWNLOAD_LIMIT:
        return None
    return (f"That is all {DAILY_DOWNLOAD_LIMIT} of your downloads for today. "
            f"You get another one {budget_renewal_phrase(conn, taken['oldest'])}.")


def budget_renewal_phrase(conn, oldest_taken_at):
    """When the oldest download in the window ages out, in words.

    The arithmetic is handed back to SQLite rather than done here so it runs on
    the same clock, in the same UTC, that stamped the row in the first place.
    Rounded rather than truncated: truncating turns "23 hours and 59 minutes"
    into "23 hours", and a wait that is quoted short is worse than one quoted
    long — the person comes back early and is refused again.
    """
    # One-argument julianday only: the Postgres compatibility layer defines
    # julianday(text) and nothing else, so the window is added here as a
    # fraction of a day rather than handed over as a modifier the way datetime()
    # takes one. Both backends read that form the same way.
    freed_in = conn.execute(
        "SELECT CAST((julianday(?) + ? - julianday('now')) * 24 + 0.5 AS INTEGER) hours",
        (oldest_taken_at, DOWNLOAD_COOLDOWN_MINUTES / 1440.0),
    ).fetchone()["hours"]
    if freed_in is None or freed_in < 1:
        return "within the hour"
    if freed_in == 1:
        return "in about an hour"
    return f"in about {freed_in} hours"


def safe_cad_target(link):
    """The external CAD URL this design may send someone to, or None.

    Checked here and not only on the way in: onshape_link predates the upload
    form's URL validation, so a row written back then can still hold anything.

    Rejected beyond the obvious wrong scheme: a netloc carrying userinfo, and
    any control character. `https://botfolio.example.com@evil.example/steal`
    parses as scheme https with a non-empty netloc and reads to a person as
    botfolio.example.com, but browsers go to evil.example — and this route is
    reached straight after someone types their password on the real sign-in
    page, which is the worst possible moment to hand them an off-site lookalike.
    The control character is the other one: urlparse strips CR and LF before
    parsing, so a link with a newline in it passed every check here and then
    raised inside Werkzeug as it built the Location header, turning a bad row
    into a 500.
    """
    if not link or link.strip() != link:
        return None
    if any(character < " " or character == "\x7f" for character in link):
        return None
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if "@" in parsed.netloc:
        return None
    return link


def recent_download_row(conn, design_id, downloader_key):
    """This person's still-counted download of this design, if there is one."""
    return conn.execute(
        "SELECT 1 FROM design_downloads WHERE design_id=? AND visitor_key=? "
        "AND downloaded_at >= datetime('now', ?)",
        (design_id, downloader_key, f"-{DOWNLOAD_COOLDOWN_MINUTES} minutes"),
    ).fetchone()


def record_design_download(conn, design_id, kind, response):
    """Count this request as a download, unless it is not one.

    One row per person per window, the same idea the visit counter already
    applies, so a resumed transfer, a double click and a re-download after a
    failed save stay one download. `kind` records how they took it; the row is
    the same either way, so someone who opens the CAD and then grabs the file
    has still taken one design.

    HEAD is counted alongside GET. Flask answers HEAD from the GET rule, and
    that used to be worth skipping because link checkers and chat-app unfurlers
    probe pasted URLs and inflated the counter. Both routes need an account now,
    so those probes never get this far — while a signed-in HEAD receives the
    whole payload on two of the three paths, since the CAD route's payload is
    its Location header and a download from bucket storage is a redirect to a
    signed URL. Skipping HEAD left the daily allowance bypassable with curl -I.
    """
    if response.status_code not in DOWNLOAD_COUNTED_STATUSES:
        return
    downloader_key = visitor_key()
    if recent_download_row(conn, design_id, downloader_key):
        return
    conn.execute("INSERT INTO design_downloads (design_id,user_id,visitor_key,kind) VALUES (?,?,?,?)", (design_id, current_user()["id"], downloader_key, kind))
    conn.commit()


@app.route("/designs/<int:design_id>/model")
# The viewer streams the stored model file itself — the same bytes /download
# serves, differing only in Content-Disposition — so leaving this open made the
# account requirement on /download decorative: changing one path segment got you
# the whole library with no account and nothing recorded. It does not spend the
# daily allowance, because looking at a design on its own page is not taking it
# and five designs is an ordinary afternoon of browsing; the account is what
# stops this being an anonymous mirror of every model on the site.
@login_required(message="Sign in to view this design in 3D.")
@ratelimit.limit("model-view", 60, 300, methods=None)
def view_design_model(design_id):
    """Issue a short-lived inline URL for the private interactive model."""
    design = db.get_db().execute(
        "SELECT model_filename,model_size_bytes,is_hidden,user_id FROM designs WHERE id=?",
        (design_id,),
    ).fetchone()
    if design is None or not design["model_filename"]:
        abort(404)
    viewer = current_user()
    if design["is_hidden"] and not (
        viewer and (viewer["is_admin"] or viewer["id"] == design["user_id"])
    ):
        abort(404)
    if is_cad_source(design["model_filename"]):
        return render_template(
            "error.html", code=415,
            message="STEP files are CAD source rather than a mesh, so the browser "
                    "viewer cannot draw one. Download it and open the solids in "
                    "your own CAD software.",
        ), 415
    if design["model_size_bytes"] and design["model_size_bytes"] > MAX_VIEW_MODEL_BYTES:
        return render_template(
            "error.html", code=413,
            message="This model is available for download but is too large for the browser viewer.",
        ), 413
    return infra_storage.send("models", design["model_filename"], as_attachment=False)


@app.route("/library")
@login_required(message="Sign in to open your library.")
def library():
    """A person's private library: every design they've saved or downloaded,
    gathered in one place off the top-bar account menu. Both lists are strictly
    the current viewer's own — no username in the URL — so nothing here can leak
    another account's saves or download history."""
    conn = db.get_db()
    viewer = current_user()
    # Saved designs, newest save first (see the profile route for the shared
    # shape of these two queries).
    saved_designs = conn.execute(
        """SELECT d.*,u.username,s.name season_name,t.number team_number,t.name team_name,
                  (SELECT COUNT(*) FROM design_likes WHERE design_id=d.id) like_count,
                  (SELECT COUNT(*) FROM design_downloads WHERE design_id=d.id) download_count,
                  (SELECT COUNT(*) FROM design_view_events WHERE design_id=d.id) visit_count
             FROM saved_designs sd JOIN designs d ON d.id=sd.design_id JOIN users u ON u.id=d.user_id
             LEFT JOIN seasons s ON s.id=d.season_id LEFT JOIN teams t ON t.id=d.team_id
            WHERE sd.user_id=? AND d.is_hidden=0 ORDER BY sd.created_at DESC""", (viewer["id"],)
    ).fetchall()
    # Download library: an inner MAX(downloaded_at) per design dedupes repeat
    # downloads and gives the most-recent-first ordering key.
    downloaded_designs = conn.execute(
        """SELECT d.*,u.username,s.name season_name,t.number team_number,t.name team_name,
                  (SELECT COUNT(*) FROM design_likes WHERE design_id=d.id) like_count,
                  (SELECT COUNT(*) FROM design_downloads WHERE design_id=d.id) download_count,
                  (SELECT COUNT(*) FROM design_view_events WHERE design_id=d.id) visit_count
             FROM (SELECT design_id, MAX(downloaded_at) last_downloaded
                     FROM design_downloads WHERE user_id=? GROUP BY design_id) lib
             JOIN designs d ON d.id=lib.design_id JOIN users u ON u.id=d.user_id
             LEFT JOIN seasons s ON s.id=d.season_id LEFT JOIN teams t ON t.id=d.team_id
            WHERE d.is_hidden=0 ORDER BY lib.last_downloaded DESC""", (viewer["id"],)
    ).fetchall()
    return render_template("library.html", saved_designs=saved_designs,
                           downloaded_designs=downloaded_designs)


@app.route("/u/<username>")
def profile(username):
    conn = db.get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE lower(username) = lower(?)", (username,)
    ).fetchone()
    if user is None or user["deleted_at"]:
        abort(404)
    if suspension_has_expired(user):
        user = restore_expired_suspension(user)
    viewer = current_user()
    if user["suspended_at"] and not (viewer and viewer["is_admin"]):
        abort(404)

    designs = conn.execute(
        """
        SELECT d.*, du.username, s.name AS season_name, t.number AS team_number, t.name AS team_name,
               (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
               (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count,
               (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count,
               (SELECT COUNT(*) FROM comments c WHERE c.design_id=d.id AND c.status='visible') comment_count
          FROM designs d JOIN users du ON du.id=d.user_id
          LEFT JOIN seasons s ON s.id = d.season_id
          LEFT JOIN teams t ON t.id = d.team_id
         WHERE (d.user_id = ? OR EXISTS(SELECT 1 FROM design_contributors dc WHERE dc.design_id=d.id AND dc.user_id=?)) AND d.is_hidden = 0
         ORDER BY d.created_at DESC, d.id DESC
        """,
        (user["id"], user["id"]),
    ).fetchall()

    featured = conn.execute(
        """SELECT d.*,du.username,s.name season_name,fd.position,t.number team_number,t.name team_name,
                  (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
                  (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count,
                  (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count
             FROM featured_designs fd JOIN designs d ON d.id=fd.design_id JOIN users du ON du.id=d.user_id
             LEFT JOIN seasons s ON s.id=d.season_id
             LEFT JOIN teams t ON t.id=d.team_id
            WHERE fd.user_id=? ORDER BY fd.position""", (user["id"],)
    ).fetchall()
    recent_comments = conn.execute(
        """SELECT c.id,c.body,c.created_at,d.id design_id,d.title design_title
             FROM comments c JOIN designs d ON d.id=c.design_id
            WHERE c.user_id=? AND c.status='visible' ORDER BY c.created_at DESC LIMIT 10""",
        (user["id"],),
    ).fetchall()
    stats = conn.execute(
        """SELECT (SELECT COUNT(*) FROM designs d WHERE d.is_hidden=0 AND (d.user_id=? OR EXISTS(SELECT 1 FROM design_contributors dc WHERE dc.design_id=d.id AND dc.user_id=?))) design_count,
                  (SELECT COUNT(*) FROM design_likes dl JOIN designs d ON d.id=dl.design_id WHERE d.user_id=?) likes_received,
                  (SELECT COUNT(*) FROM design_downloads dd JOIN designs d ON d.id=dd.design_id WHERE d.user_id=?) downloads,
                  (SELECT COUNT(*) FROM comment_helpful ch JOIN comments c ON c.id=ch.comment_id WHERE c.user_id=? AND c.status='visible') helpful_answers,
                  (SELECT COUNT(*) FROM saved_designs WHERE user_id=?) saved_count""",
        (user["id"], user["id"], user["id"], user["id"], user["id"], user["id"]),
    ).fetchone()

    saved_ai_chats = []
    # Saved designs and the download library now live on the dedicated /library
    # page (reached from the top-bar account menu), so the profile only still
    # renders the saved AI chats section for its owner.
    if viewer and viewer["id"] == user["id"]:
        saved_chat_rows = conn.execute(
            """SELECT af.*,d.title design_title
                 FROM ai_feedback af JOIN designs d ON d.id=af.design_id
                WHERE af.requester_id=? AND af.saved_at IS NOT NULL AND d.is_hidden=0
                ORDER BY af.saved_at DESC,af.id DESC""",
            (user["id"],),
        ).fetchall()
        for row in saved_chat_rows:
            chat = dict(row)
            try:
                chat["rubric"] = json.loads(row["rubric_json"] or "{}")
            except (ValueError, TypeError):
                chat["rubric"] = {}
            saved_ai_chats.append(chat)

    teams = conn.execute(
        """
        SELECT t.*, m.role FROM teams t
          JOIN memberships m ON m.team_id = t.id
         WHERE m.user_id = ?
         ORDER BY t.number
        """,
        (user["id"],),
    ).fetchall()

    try:
        social_links = json.loads(user["social_links"] or "{}")
    except (ValueError, TypeError):
        social_links = {}
    can_edit = bool(viewer) and (viewer["id"] == user["id"] or viewer["is_admin"])
    authored_design_count = conn.execute(
        "SELECT COUNT(*) AS c FROM designs WHERE user_id=?", (user["id"],)
    ).fetchone()["c"]
    return render_template("profile.html", user=user, designs=designs, teams=teams,
                           authored_design_count=authored_design_count,
                           social_links=social_links, can_edit=can_edit,
                           featured=featured, recent_comments=recent_comments, stats=stats,
                           saved_ai_chats=saved_ai_chats,
                           is_own_profile=bool(viewer and viewer["id"] == user["id"]),
                           specialties=[x.strip() for x in (user["interests"] or user["specialties"]).split(",") if x.strip()],
                           cad_tools=[x.strip() for x in user["cad_tools"].split(",") if x.strip()])


@app.route("/u/<username>/moderate", methods=["POST"])
@admin_required
def moderate_user(username):
    conn = db.get_db()
    target = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    if target is None:
        abort(404)
    action = request.form.get("action")
    reason = (request.form.get("reason") or "Administrator action").strip()[:500]
    if action not in {"warn", "suspend", "restore", "ban"} or not reason:
        abort(400)
    if target["id"] == current_user()["id"] and action in {"suspend", "ban"}:
        abort(400, "Administrators cannot restrict their own active account.")
    duration_label = None
    if action == "warn":
        pass
    elif action == "suspend":
        durations = {
            "1_hour": (timedelta(hours=1), "1 hour"),
            "24_hours": (timedelta(hours=24), "24 hours"),
            "3_days": (timedelta(days=3), "3 days"),
            "7_days": (timedelta(days=7), "7 days"),
            "14_days": (timedelta(days=14), "14 days"),
            "30_days": (timedelta(days=30), "30 days"),
        }
        duration_key = request.form.get("suspension_duration") or ""
        if duration_key not in durations:
            abort(400, "Choose a valid suspension duration.")
        duration, duration_label = durations[duration_key]
        suspended_until = (datetime.now(timezone.utc) + duration).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET suspended_at=datetime('now'),suspended_until=?,banned_at=NULL WHERE id=?",
            (suspended_until, target["id"]),
        )
    elif action == "restore":
        conn.execute("UPDATE users SET suspended_at=NULL,suspended_until=NULL,banned_at=NULL WHERE id=?", (target["id"],))
    elif action == "ban":
        conn.execute("UPDATE users SET banned_at=datetime('now'),suspended_at=datetime('now'),suspended_until=NULL WHERE id=?", (target["id"],))
    audit_reason = reason if not duration_label else f"{reason} (Suspension duration: {duration_label})"
    conn.execute("INSERT INTO moderation_actions(admin_id,target_type,target_id,action,reason) VALUES (?,?,?,?,?)",
                 (current_user()["id"], "user", str(target["id"]), action, audit_reason))
    conn.commit()
    if action == "warn":
        email_service.send_email(
            to_email=target["email"], to_name=target["username"],
            subject="A warning from Botfolio moderation",
            heading="Botfolio account warning",
            message=(f"A Botfolio administrator issued this warning:\n\n{reason}\n\n"
                     "Please review the Community Rules. Contact support if you believe this was sent in error."),
            event_type="moderation_warning",
        )
    elif action in {"suspend", "ban", "restore"}:
        send_access_status_email(target, action, reason, duration_label)
    flash("Account moderation updated.", "success")
    return redirect(url_for("profile", username=username))


# Let a user, or an administrator, safely edit durable profile information.
@app.route("/u/<username>/edit", methods=["GET", "POST"])
@login_required
def edit_profile(username):
    conn = db.get_db()
    profile_user = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    if profile_user is None:
        abort(404)
    viewer = current_user()
    if viewer["id"] != profile_user["id"] and not viewer["is_admin"]:
        abort(403)
    if request.method == "POST":
        try:
            website = clean_url(request.form.get("website_url"))
            contact_email = (request.form.get("contact_email") or "").strip()
            if contact_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact_email):
                raise ValueError("Enter a valid public contact email address.")
            links = {}
            for label in ("instagram", "youtube", "github"):
                value = clean_url(request.form.get(label))
                if value:
                    links[label] = value
            bio = (request.form.get("bio") or "").strip()
            display_name = (request.form.get("display_name") or "").strip()[:80]
            location = (request.form.get("location") or "").strip()
            tagline = (request.form.get("tagline") or "").strip()[:120]
            specialties = ", ".join(dict.fromkeys(x.strip() for x in (request.form.get("specialties") or "").split(",") if x.strip()))[:300]
            interests = [x for x in request.form.getlist("interests") if x in ROBOTICS_INTERESTS]
            cad_tools = ", ".join(dict.fromkeys(x.strip() for x in (request.form.get("cad_tools") or "").split(",") if x.strip()))[:300]
            moderate_public_content(
                texts=[display_name, bio, location, tagline, specialties, cad_tools, *interests],
                use_api=not app.testing,
            )
            image = profile_user["profile_image"]
            upload = request.files.get("profile_image")
            if upload and upload.filename:
                image = save_image_upload(upload)
            ftc_role = request.form.get("ftc_role") or None
            if ftc_role not in FTC_ROLES and ftc_role is not None:
                raise ValueError("Choose a valid robotics role.")
            conn.execute("UPDATE users SET display_name=?,bio=?,location=?,contact_email=?,website_url=?,social_links=?,profile_image=?,tagline=?,specialties=?,interests=?,cad_tools=?,ftc_role=? WHERE id=?",
                         (display_name, bio, location,
                          contact_email, website, json.dumps(links), image, tagline, specialties, ", ".join(interests), cad_tools, ftc_role, profile_user["id"]))
            selected = []
            for raw_id in request.form.getlist("featured_designs")[:6]:
                try: selected.append(int(raw_id))
                except ValueError: pass
            owned = {row["id"] for row in conn.execute("SELECT id FROM designs WHERE user_id=?", (profile_user["id"],))}
            conn.execute("DELETE FROM featured_designs WHERE user_id=?", (profile_user["id"],))
            for position, design_id in enumerate((i for i in selected if i in owned), 1):
                conn.execute("INSERT INTO featured_designs(user_id,design_id,position) VALUES (?,?,?)", (profile_user["id"], design_id, position))
            conn.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("profile", username=profile_user["username"]))
        except ValueError as exc:
            flash(str(exc), "error")
    try:
        links = json.loads(profile_user["social_links"] or "{}")
    except (ValueError, TypeError):
        links = {}
    owned_designs = conn.execute("SELECT id,title FROM designs WHERE user_id=? ORDER BY created_at DESC", (profile_user["id"],)).fetchall()
    selected_designs = {row["design_id"] for row in conn.execute("SELECT design_id FROM featured_designs WHERE user_id=?", (profile_user["id"],))}
    return render_template("edit_profile.html", user=profile_user, links=links,
                           owned_designs=owned_designs, selected_designs=selected_designs,
                           roles=FTC_ROLES, interest_choices=ROBOTICS_INTERESTS,
                           selected_interests={x.strip() for x in (profile_user["interests"] or "").split(",") if x.strip()})


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def send_verification_email(user_id, email, username):
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    conn = db.get_db()
    conn.execute("DELETE FROM email_verification_tokens WHERE user_id=? AND used_at IS NULL", (user_id,))
    conn.execute("INSERT INTO email_verification_tokens(user_id,token_hash,expires_at) VALUES (?,?,datetime('now','+24 hours'))", (user_id, token_hash))
    conn.commit()
    return email_service.send_email(
        to_email=email, to_name=username, subject="Verify your Botfolio email",
        heading="Verify your email",
        message=(
            f"Hi {username},\n\n"
            "Thanks for joining Botfolio.\n\n"
            "Please verify your email address before uploading designs, "
            "commenting, or participating in the community.\n\n"
            "If you didn't create a Botfolio account, you can ignore this email.\n\n"
            "Thanks,\nBotfolio\n\nbotfoliohq.com"
        ),
        action_url=url_for("verify_email", token=raw_token, _external=True),
        action_text="Verify Email", event_type="email_verification",
        greeting=f"Hi {username},",
        intro="Thanks for joining Botfolio.",
        purpose=(
            "Please verify your email address before uploading designs, "
            "commenting, or participating in the community."
        ),
        security_notice=(
            "If you didn't create a Botfolio account, you can ignore this email."
        ),
        signoff="Thanks,\nBotfolio",
        footer="This email was sent because this address was used to create a Botfolio account.",
    )


# Account and authentication routes are kept together in their own Blueprint.
from routes import register_blueprint_compat
from routes.auth import auth_bp

register_blueprint_compat(app, auth_bp)

# Sign in with Google lives beside them but in its own module: the OAuth
# callback's account-resolution rules are long enough to bury auth.py.
from routes.google_signin import google_bp

register_blueprint_compat(app, google_bp)


# --------------------------------------------------------------------------
# Submitting and editing designs
# --------------------------------------------------------------------------

from routes.designs import (
    _design_taxonomy_error, authorize_model_upload, complete_model_upload,
    designs_bp, edit_design, finalize_model_upload, submit, submit_link,
)

register_blueprint_compat(app, designs_bp)

from routes.engineering import engineering_bp

register_blueprint_compat(app, engineering_bp)

from routes.academy import academy_bp

register_blueprint_compat(app, academy_bp)


@app.route("/designs/<int:design_id>/delete", methods=["POST"])
@login_required
def delete_design(design_id):
    design = _owned_design_or_404(design_id)
    conn = db.get_db()
    image_filenames = [row["filename"] for row in conn.execute(
        "SELECT filename FROM design_images WHERE design_id=?", (design_id,)
    ).fetchall()]
    conn.execute(
        "UPDATE users SET storage_used_bytes=CASE WHEN storage_used_bytes>=? "
        "THEN storage_used_bytes-? ELSE 0 END WHERE id=?",
        (design["storage_bytes"], design["storage_bytes"], design["user_id"]),
    )
    conn.execute("DELETE FROM designs WHERE id = ?", (design_id,))
    conn.commit()
    for filename in set(image_filenames + [design["image_filename"]]):
        delete_asset(UPLOAD_DIR, filename)
    delete_asset(MODEL_DIR, design["model_filename"])
    flash("Design deleted.", "success")
    return redirect(url_for("profile", username=current_user()["username"]))


@app.route("/designs/<int:design_id>/moderate", methods=["POST"])
@admin_required
def moderate_design(design_id):
    action = request.form.get("action")
    reason = (request.form.get("reason") or "").strip()[:500]
    if action not in {"hide", "restore", "delete"} or not reason:
        abort(400)
    conn = db.get_db()
    design = conn.execute("SELECT * FROM designs WHERE id=?", (design_id,)).fetchone()
    if design is None:
        abort(404)
    if action in {"hide", "restore"}:
        conn.execute(
            "UPDATE designs SET is_hidden=?,updated_at=datetime('now') WHERE id=?",
            (1 if action == "hide" else 0, design_id),
        )
    else:
        image_filenames = {row["filename"] for row in conn.execute(
            "SELECT filename FROM design_images WHERE design_id=?", (design_id,)
        ).fetchall()} | {design["image_filename"]}
        conn.execute(
            "UPDATE users SET storage_used_bytes=CASE WHEN storage_used_bytes>=? THEN storage_used_bytes-? ELSE 0 END WHERE id=?",
            (design["storage_bytes"], design["storage_bytes"], design["user_id"]),
        )
        conn.execute("DELETE FROM designs WHERE id=?", (design_id,))
    conn.execute(
        "INSERT INTO moderation_actions(admin_id,target_type,target_id,action,reason) VALUES (?,?,?,?,?)",
        (current_user()["id"], "design", str(design_id), action, reason),
    )
    conn.commit()
    if action == "delete":
        for filename in image_filenames:
            delete_asset(UPLOAD_DIR, filename)
        delete_asset(MODEL_DIR, design["model_filename"])
        flash("Design permanently deleted and its active stored files removed.", "success")
        return redirect(url_for("comment_moderation"))
    flash("Design restored." if action == "restore" else "Design hidden immediately.", "success")
    if request.form.get("return_to") == "moderation":
        return redirect(url_for("comment_moderation"))
    return redirect(url_for("design_detail", design_id=design_id))


# --------------------------------------------------------------------------
# Tags and voting
# --------------------------------------------------------------------------

@app.route("/tags")
def tag_directory():
    query = (request.args.get("q") or "").strip()[:80]
    tags = db.get_db().execute(
        """
        SELECT t.id, t.name, t.created_at,
               COUNT(dt.design_id) AS uses,
               u.username AS coined_by
          FROM tags t
          LEFT JOIN design_tags dt ON dt.tag_id = t.id
          LEFT JOIN users u ON u.id = t.created_by
         WHERE (? = '' OR t.name LIKE ? COLLATE NOCASE)
         GROUP BY t.id, t.name, t.created_at, u.username
         ORDER BY uses DESC, t.name ASC
        """, (query, f"%{query}%")
    ).fetchall()
    return render_template("tags.html", tags=tags, q=query)


@app.route("/tags", methods=["POST"])
@login_required
def create_tag():
    name = normalize_tag(request.form.get("name") or "")
    if not name or len(name) > MAX_TAG_LENGTH:
        flash(f"Tags must be 1-{MAX_TAG_LENGTH} characters.", "error")
        return redirect(url_for("tag_directory"))
    try:
        moderate_public_content(texts=[name], use_api=not app.testing)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tag_directory"))

    conn = db.get_db()
    recent = conn.execute("SELECT COUNT(*) n FROM tags WHERE created_by=? AND created_at >= datetime('now','-1 hour')", (current_user()["id"],)).fetchone()["n"]
    if recent >= NEW_TAG_LIMIT_PER_HOUR:
        flash("You are creating tags too quickly. Please wait an hour.", "error")
        return redirect(url_for("tag_directory"))
    existing = find_tag(conn, name)
    if existing:
        flash(f"“{display_tag(existing['name'])}” already exists.", "error")
    else:
        conn.execute(
            "INSERT INTO tags (name, key, created_by) VALUES (?, ?, ?)",
            (name, tag_key(name), current_user()["id"]),
        )
        conn.commit()
        flash(f"Added “{display_tag(name)}” to the tag vocabulary.", "success")
    return redirect(url_for("tag_directory"))


@app.route("/designs/<int:design_id>/tags", methods=["POST"])
@login_required
def add_design_tag(design_id):
    conn = db.get_db()
    if conn.execute("SELECT 1 FROM designs WHERE id = ? AND is_hidden = 0", (design_id,)).fetchone() is None:
        abort(404)

    added = 0
    try:
        moderate_public_content(
            texts=[request.form.get("name") or ""], use_api=not app.testing
        )
        for raw in (request.form.get("name") or "").split(","):
            if raw.strip() and attach_tag(design_id, raw, current_user()["id"]):
                added += 1
    except ValueError as exc:
        conn.rollback(); flash(str(exc), "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#tags")
    conn.commit()

    flash("Tag added." if added else "That tag wasn't valid.",
          "success" if added else "error")
    return redirect(url_for("design_detail", design_id=design_id))


@app.route("/designs/<int:design_id>/tags/<int:tag_id>/vote", methods=["POST"])
@login_required
def vote_tag(design_id, tag_id):
    value = request.form.get("value", type=int)
    if value not in (-1, 1):
        abort(400)

    conn = db.get_db()
    linked = conn.execute(
        "SELECT 1 FROM design_tags dt JOIN designs d ON d.id = dt.design_id "
        "WHERE dt.design_id = ? AND dt.tag_id = ? AND d.is_hidden = 0",
        (design_id, tag_id),
    ).fetchone()
    if linked is None:
        abort(404)

    user_id = current_user()["id"]
    existing = conn.execute(
        "SELECT value FROM tag_votes WHERE user_id = ? AND design_id = ? AND tag_id = ?",
        (user_id, design_id, tag_id),
    ).fetchone()

    if existing and existing["value"] == value:
        # Clicking your existing vote again clears it.
        conn.execute(
            "DELETE FROM tag_votes WHERE user_id = ? AND design_id = ? AND tag_id = ?",
            (user_id, design_id, tag_id),
        )
    else:
        conn.execute(
            "INSERT INTO tag_votes (user_id, design_id, tag_id, value) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_id, design_id, tag_id) DO UPDATE SET value = ?",
            (user_id, design_id, tag_id, value, value),
        )
    cleanup_low_score_tags(conn, design_id, tag_id)
    conn.commit()
    if request.accept_mimetypes.best == "application/json":
        result = conn.execute(
            "SELECT COALESCE(SUM(value), 0) score, "
            "(SELECT value FROM tag_votes WHERE user_id=? AND design_id=? AND tag_id=?) my_vote "
            "FROM tag_votes WHERE design_id=? AND tag_id=?",
            (user_id, design_id, tag_id, design_id, tag_id),
        ).fetchone()
        return jsonify(score=result["score"], my_vote=result["my_vote"])
    return redirect(url_for("design_detail", design_id=design_id) + "#tags")


@app.route("/api/tags")
def search_tags():
    query = normalize_tag(request.args.get("q") or "")
    rows = db.get_db().execute("SELECT id,name FROM tags WHERE name LIKE ? ORDER BY name LIMIT 12", (f"%{query}%",)).fetchall()
    # Capitalised for the suggestion list. Whatever the user picks is
    # fingerprinted again on submit, so it still lands on the same tag.
    return {"tags": [{"id": row["id"], "name": display_tag(row["name"])} for row in rows]}


@app.route("/designs/<int:design_id>/tags/<int:tag_id>/remove", methods=["POST"])
@admin_required
def remove_design_tag(design_id, tag_id):
    conn = db.get_db(); conn.execute("DELETE FROM design_tags WHERE design_id=? AND tag_id=?", (design_id, tag_id)); conn.commit()
    flash("Tag removed from this design.", "success")
    return redirect(url_for("design_detail", design_id=design_id) + "#tags")


# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

def _team_program(raw, default="ftc"):
    program = (raw or default).strip().lower()
    return program if program in TEAM_PROGRAMS else None


def _team_registry(program):
    return {"ftc": ftc_teams, "frc": frc_teams}[program]


def _team_url(team):
    return url_for(
        "team_detail", program=team["program"], number=team["number"]
    )


def _find_team(conn, program, number, *, claimed_only=False):
    status = " AND profile_status='claimed'" if claimed_only else ""
    return conn.execute(
        f"SELECT * FROM teams WHERE program=? AND number=?{status}",
        (program, number),
    ).fetchone()

@app.route("/teams")
def team_list():
    query = (request.args.get("q") or "").strip()[:80]
    program = _team_program(request.args.get("program"), default="")
    selected_program = program or ""

    # A numeric search can go straight to the authoritative profile when the
    # visitor has picked a program. With "All" selected we show both possible
    # identities instead of guessing whether 254 means FTC or FRC.
    if query.isdigit() and program:
        return redirect(url_for("team_detail", program=program, number=int(query)))

    conn = db.get_db()
    founding_claimed = conn.execute(
        "SELECT COUNT(*) n FROM teams WHERE program='ftc' AND founding_rank IS NOT NULL"
    ).fetchone()["n"]

    if query:
        api_error = False
        programs = [program] if program else list(TEAM_PROGRAMS)
        results = []
        for code in programs:
            remote = []
            try:
                remote = _team_registry(code).search(query, limit=25)
            except (ftc_teams.FtcApiError, frc_teams.FrcApiError):
                api_error = True
            for team in remote:
                team = dict(team)
                team["program"] = code
                local = _find_team(conn, code, team["number"], claimed_only=True)
                team["on_botfolio"] = local is not None
                team["banner_image"] = local["banner_image"] if local else None
                team["design_count"] = conn.execute(
                    "SELECT COUNT(*) n FROM designs WHERE team_id=? AND is_hidden=0",
                    (local["id"],),
                ).fetchone()["n"] if local else None
                results.append(team)

        # FRC's official API supports direct number lookup but not a team-name
        # query. Local Botfolio profiles fill that gap, and also make FTC search
        # useful during a registry outage.
        like = f"%{query}%"
        params = [like, like]
        program_sql = ""
        if program:
            program_sql = " AND t.program=?"
            params.append(program)
        local_rows = conn.execute(
            """SELECT t.*,
                      (SELECT COUNT(*) FROM designs d WHERE d.team_id=t.id AND d.is_hidden=0) design_count
                 FROM teams t
                WHERE t.profile_status='claimed'
                  AND (t.name LIKE ? OR CAST(t.number AS TEXT) LIKE ?)"""
            + program_sql + " ORDER BY t.program,t.number LIMIT 25",
            params,
        ).fetchall()
        seen = {(team["program"], team["number"]) for team in results}
        for row in local_rows:
            if (row["program"], row["number"]) not in seen:
                item = dict(row)
                item["location"] = row["region"]
                item["on_botfolio"] = True
                results.append(item)
        return render_template(
            "teams.html", teams=None, q=query, results=results, api_error=api_error,
            founding_claimed=founding_claimed, founding_limit=FOUNDING_TEAM_LIMIT,
            programs=TEAM_PROGRAMS, selected_program=selected_program,
        )

    params = []
    program_sql = ""
    if program:
        program_sql = " AND t.program=?"
        params.append(program)
    teams = conn.execute(
        """
        SELECT t.*, COUNT(DISTINCT m.user_id) AS member_count,
               COUNT(DISTINCT d.id) AS design_count
          FROM teams t
          LEFT JOIN memberships m ON m.team_id = t.id
          LEFT JOIN designs d ON d.team_id=t.id AND d.is_hidden=0
         WHERE t.profile_status='claimed'""" + program_sql + """
         GROUP BY t.id
         ORDER BY t.program,t.number
        """, params
    ).fetchall()
    return render_template("teams.html", teams=teams, q="", results=None, api_error=False,
                           founding_claimed=founding_claimed, founding_limit=FOUNDING_TEAM_LIMIT,
                           programs=TEAM_PROGRAMS, selected_program=selected_program)


@app.route("/my-team")
@login_required
def my_team():
    """Send a member to their team. One team goes straight there; several land on
    the profile's Teams section; none routes to the create/claim flow."""
    user = current_user()
    conn = db.get_db()
    teams = conn.execute(
        "SELECT t.program,t.number FROM teams t JOIN memberships m ON m.team_id=t.id "
        "WHERE m.user_id=? ORDER BY (m.role='owner') DESC, t.number",
        (user["id"],),
    ).fetchall()
    if not teams:
        return redirect(url_for("team_list"))
    if len(teams) == 1:
        return redirect(_team_url(teams[0]))
    return redirect(url_for("profile", username=user["username"]) + "#teams")


@app.route("/teams", methods=["POST"])
@login_required
def create_team():
    program = _team_program(request.form.get("program"))
    number = request.form.get("number", type=int)
    name = (request.form.get("name") or "").strip()

    if not program or not number or number <= 0 or not name:
        flash("A team needs a positive number and a name.", "error")
        return redirect(url_for("team_list"))
    try:
        moderate_public_content(
            texts=[name, request.form.get("region") or ""], use_api=not app.testing
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("team_list"))

    conn = db.get_db()
    user_id = current_user()["id"]
    invite_code = secrets.token_urlsafe(6)
    existing = _find_team(conn, program, number)
    if existing and existing["profile_status"] == "claimed":
        flash(f"Team {number} has already been claimed.", "error")
        return redirect(url_for("team_list"))
    if existing:
        has_attributions = conn.execute(
            "SELECT 1 FROM designs WHERE team_id=? AND uploaded_by_admin=1 LIMIT 1",
            (existing["id"],),
        ).fetchone()
        if has_attributions and request.form.get("accept_attributions") != "accepted":
            flash("Confirm that the credited designs belong to your team before claiming this page.", "error")
            return redirect(url_for("team_detail", program=program, number=number))
        conn.execute(
            """UPDATE teams SET name=?,region=?,owner_id=?,invite_code=?,
                      profile_status='claimed' WHERE id=?""",
            (name, (request.form.get("region") or "").strip(), user_id,
             invite_code, existing["id"]),
        )
        team_id = existing["id"]
        conn.execute(
            "UPDATE designs SET team_attribution_accepted=1 WHERE team_id=?",
            (team_id,),
        )
    else:
        team_id = conn.execute(
            "INSERT INTO teams (program,number, name, region, owner_id, invite_code, is_founding,profile_status) "
            "VALUES (?, ?, ?, ?, ?, ?, 0,'claimed')",
            (program, number, name, (request.form.get("region") or "").strip(), user_id,
             invite_code),
        ).lastrowid
    conn.execute(
        "INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'owner')",
        (user_id, team_id),
    )
    qualify_founding_team(conn, team_id)
    conn.commit()
    flash(f"{TEAM_PROGRAMS[program]} Team {number} claimed. Your invite code is {invite_code}", "success")
    return redirect(url_for("team_detail", program=program, number=number))


@app.route("/u/<username>/convert-to-team", methods=["POST"])
@admin_required
def convert_profile_to_team(username):
    """Admin cleanup for a personal profile that is really a robotics team.

    Creates (or claims) a team page owned by the profile's user and re-homes the
    team-looking content onto it. Design authorship (designs.user_id) is always
    preserved — only team_id moves. Two modes:
      * convert - also blanks the moved fields off the personal profile, so the
                  person profile no longer reads as a team.
      * move    - leaves the personal profile untouched (content is copied).
    Both require a reason and are written to the moderation audit log."""
    conn = db.get_db()
    profile_user = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (username,)).fetchone()
    if profile_user is None:
        abort(404)

    mode = request.form.get("mode")
    if mode not in {"convert", "move"}:
        mode = "convert"
    number = request.form.get("number", type=int)
    name = (request.form.get("name") or "").strip()
    reason = (request.form.get("reason") or "").strip()

    if not reason:
        flash("A reason is required and is saved to the audit log.", "error")
        return redirect(url_for("profile", username=username))
    if not number or number <= 0 or not name:
        flash("Enter the team number and name for the new team page.", "error")
        return redirect(url_for("profile", username=username))
    try:
        moderate_public_content(texts=[name], use_api=not app.testing)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profile", username=username))

    # This legacy admin conversion starts from the user's FTC profile field, so
    # it intentionally creates or updates an FTC page.
    existing = conn.execute(
        "SELECT * FROM teams WHERE program='ftc' AND number=?", (number,)
    ).fetchone()
    if existing and existing["profile_status"] == "claimed":
        flash(f"Team {number} has already been claimed, so a new page can't be created for it.", "error")
        return redirect(url_for("profile", username=username))

    invite_code = secrets.token_urlsafe(6)
    social_links = profile_user["social_links"] or "{}"
    if existing:
        conn.execute(
            """UPDATE teams SET name=?, biography=?, profile_image=?, website_url=?,
                      social_links=?, owner_id=?, invite_code=?, profile_status='claimed'
                 WHERE id=?""",
            (name, profile_user["bio"] or "", profile_user["profile_image"],
             profile_user["website_url"], social_links, profile_user["id"],
             invite_code, existing["id"]),
        )
        team_id = existing["id"]
    else:
        team_id = conn.execute(
            """INSERT INTO teams (program, number, name, biography, profile_image, website_url,
                      social_links, owner_id, invite_code, is_founding, profile_status)
               VALUES ('ftc', ?, ?, ?, ?, ?, ?, ?, ?, 0, 'claimed')""",
            (number, name, profile_user["bio"] or "", profile_user["profile_image"],
             profile_user["website_url"], social_links, profile_user["id"], invite_code),
        ).lastrowid

    # The profile owner becomes the team owner; keep any existing membership row
    # (only its role is promoted). ON CONFLICT — rather than SQLite-only
    # INSERT OR REPLACE — is portable to the Postgres translation layer.
    conn.execute(
        "INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'owner') "
        "ON CONFLICT (user_id, team_id) DO UPDATE SET role='owner'",
        (profile_user["id"], team_id),
    )
    # Re-credit the user's designs to the team. user_id (authorship) is untouched.
    moved = conn.execute(
        "UPDATE designs SET team_id=?, team_attribution_accepted=1 WHERE user_id=?",
        (team_id, profile_user["id"]),
    ).rowcount

    if mode == "convert":
        conn.execute(
            "UPDATE users SET bio='', profile_image=NULL, website_url=NULL, social_links='{}' WHERE id=?",
            (profile_user["id"],),
        )

    action = "convert_profile_to_team" if mode == "convert" else "move_team_info_to_team"
    conn.execute(
        "INSERT INTO moderation_actions (admin_id, target_type, target_id, action, reason) "
        "VALUES (?, 'user', ?, ?, ?)",
        (current_user()["id"], str(profile_user["id"]), action, reason),
    )
    qualify_founding_team(conn, team_id)
    conn.commit()
    flash(
        f"Created Team {number} from @{username}'s profile. "
        f"{moved} design(s) re-credited to the team; authorship preserved.",
        "success",
    )
    return redirect(url_for("team_detail", program="ftc", number=number))


@app.route("/teams/<int:number>", defaults={"program": "ftc"})
@app.route("/teams/<program>/<int:number>")
def team_detail(number, program):
    program = _team_program(program)
    if program is None:
        abort(404)
    conn = db.get_db()
    team = _find_team(conn, program, number)
    if team is None:
        # The registry adapter keeps program-specific API details out of the
        # profile route. FTC and FRC therefore fail soft in exactly the same way.
        lookup = _team_registry(program).describe(number)
        status = {"found": 200, "absent": 404, "error": 503}[lookup["state"]]
        return render_template(
            "team_unclaimed.html", number=number, program=program,
            program_label=TEAM_PROGRAMS[program], lookup=lookup,
        ), status

    if team["profile_status"] == "reference":
        credited_designs = conn.execute(
            """SELECT d.id,d.title,d.image_filename,d.created_at
                 FROM designs d WHERE d.team_id=? AND d.is_hidden=0
                 ORDER BY d.created_at DESC""",
            (team["id"],),
        ).fetchall()
        return render_template(
            "team_reference.html", team=team, designs=credited_designs,
            program_label=TEAM_PROGRAMS[program],
        )

    members = conn.execute(
        "SELECT u.id, u.username, u.display_name, u.ftc_role, u.specialties, m.role, m.joined_at FROM memberships m "
        "JOIN users u ON u.id = m.user_id WHERE m.team_id = ? "
        "ORDER BY m.role DESC, u.username",
        (team["id"],),
    ).fetchall()
    designs = conn.execute(
        """SELECT d.*,s.name season_name,s.year_label,s.sort_order,
                  t.number team_number,t.name team_name,
                  (SELECT COUNT(*) FROM design_likes dl WHERE dl.design_id=d.id) like_count,
                  (SELECT COUNT(*) FROM design_view_events dv WHERE dv.design_id=d.id) visit_count,
                  (SELECT COUNT(*) FROM design_downloads dd WHERE dd.design_id=d.id) download_count
             FROM designs d LEFT JOIN seasons s ON s.id=d.season_id
             LEFT JOIN teams t ON t.id=d.team_id
            WHERE d.team_id=? AND d.is_hidden=0 ORDER BY s.sort_order DESC,d.created_at DESC""",
        (team["id"],),
    ).fetchall()
    design_seasons = []
    grouped = {}
    for design in designs:
        key = design["season_id"]
        if key not in grouped:
            group = {"name": design["season_name"] or "Unspecified season",
                     "year_label": design["year_label"] or "", "designs": []}
            grouped[key] = group
            design_seasons.append(group)
        grouped[key]["designs"].append(design)
    team_stats = team_service.aggregate_design_stats(designs)

    user = current_user()
    is_member = bool(user) and any(m["username"] == user["username"] for m in members)
    is_owner = bool(user) and team["owner_id"] == user["id"]
    is_manager = bool(user) and any(m["username"] == user["username"] and m["role"] in {"owner", "manager"} for m in members)
    can_edit = bool(user) and (is_manager or user["is_admin"])
    pending_membership = None
    if user and not is_member:
        pending_membership = conn.execute(
            """SELECT kind FROM team_membership_requests
                WHERE team_id=? AND user_id=? AND status='pending'
                ORDER BY created_at DESC,id DESC LIMIT 1""",
            (team["id"], user["id"]),
        ).fetchone()
    pending_invitations = []
    if is_owner:
        pending_invitations = conn.execute(
            """SELECT r.id,r.created_at,u.username FROM team_membership_requests r
                 JOIN users u ON u.id=r.user_id
                WHERE r.team_id=? AND r.kind='invitation' AND r.status='pending'
                ORDER BY r.created_at DESC,r.id DESC""",
            (team["id"],),
        ).fetchall()
    pending_attribution_count = conn.execute(
        "SELECT COUNT(*) n FROM designs WHERE team_id=? AND team_attribution_accepted=0",
        (team["id"],),
    ).fetchone()["n"]

    def decoded_links(value):
        try:
            return json.loads(value or "{}")
        except (ValueError, TypeError):
            return {}

    return render_template(
        "team.html", team=team, members=members, designs=designs, design_seasons=design_seasons,
        team_stats=team_stats,
        is_member=is_member, is_owner=is_owner, can_edit=can_edit,
        pending_membership=pending_membership,
        pending_invitations=pending_invitations,
        pending_attribution_count=pending_attribution_count,
        social_links=decoded_links(team["social_links"]), other_links=decoded_links(team["other_links"]),
        founding_claimed=conn.execute("SELECT COUNT(*) n FROM teams WHERE program='ftc' AND founding_rank IS NOT NULL").fetchone()["n"],
        founding_limit=FOUNDING_TEAM_LIMIT,
        program_label=TEAM_PROGRAMS[program],
        invite_url=url_for("register", ref=f"team-{team['number']}", _external=True),
    )


@app.route("/teams/<int:number>/attributions/accept", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/attributions/accept", methods=["POST"])
@login_required
def accept_team_attributions(number, program):
    """Let a team manager confirm admin-supplied design credits."""
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number, claimed_only=True) if program else None
    if team is None:
        abort(404)
    user = current_user()
    role = conn.execute(
        "SELECT role FROM memberships WHERE team_id=? AND user_id=?",
        (team["id"], user["id"]),
    ).fetchone()
    if not user["is_admin"] and (not role or role["role"] not in {"owner", "manager"}):
        abort(403)
    conn.execute(
        "UPDATE designs SET team_attribution_accepted=1 "
        "WHERE team_id=? AND team_attribution_accepted=0",
        (team["id"],),
    )
    qualify_founding_team(conn, team["id"])
    conn.commit()
    flash("Team design credits accepted.", "success")
    return redirect(_team_url(team))


# Allow owners, managers, and administrators to update a team profile.
@app.route("/teams/<int:number>/edit", defaults={"program": "ftc"}, methods=["GET", "POST"])
@app.route("/teams/<program>/<int:number>/edit", methods=["GET", "POST"])
@login_required
def edit_team(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    user = current_user()
    role = conn.execute("SELECT role FROM memberships WHERE team_id=? AND user_id=?", (team["id"], user["id"])).fetchone()
    if not user["is_admin"] and (not role or role["role"] not in {"owner", "manager"}):
        abort(403)
    if request.method == "POST":
        try:
            website = clean_url(request.form.get("website_url"))
            links = {}
            for label in ("instagram", "youtube", "github"):
                value = clean_url(request.form.get(label))
                if value: links[label] = value
            name = (request.form.get("name") or "").strip()
            region = (request.form.get("region") or "").strip()
            biography = (request.form.get("biography") or "").strip()
            moderate_public_content(
                texts=[name, region, biography], use_api=not app.testing
            )
            logo = team["profile_image"]
            banner = team["banner_image"]
            if request.files.get("profile_image") and request.files["profile_image"].filename:
                logo = save_image_upload(request.files["profile_image"])
            if request.files.get("banner_image") and request.files["banner_image"].filename:
                banner = save_image_upload(request.files["banner_image"])
            new_number = request.form.get("number", type=int)
            if not name or not new_number or new_number <= 0:
                raise ValueError("Team name and a positive team number are required.")
            conn.execute("UPDATE teams SET name=?,number=?,region=?,biography=?,profile_image=?,banner_image=?,website_url=?,social_links=? WHERE id=?", (name,new_number,region,biography,logo,banner,website,json.dumps(links),team["id"]))
            qualify_founding_team(conn, team["id"])
            conn.commit(); flash("Team profile updated.", "success")
            return redirect(url_for("team_detail", program=program, number=new_number))
        except (ValueError, OSError) as exc:
            flash(str(exc), "error")
    try: links = json.loads(team["social_links"] or "{}")
    except ValueError: links = {}
    return render_template("edit_team.html", team=team, links=links)


# Transfer ownership only to an existing member of the same team.
@app.route("/teams/<int:number>/transfer", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/transfer", methods=["POST"])
@login_required
def transfer_team(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    user = current_user()
    if team["owner_id"] != user["id"]:
        abort(403)
    new_owner_id = request.form.get("new_owner_id", type=int)
    member = conn.execute("SELECT 1 FROM memberships WHERE team_id=? AND user_id=?", (team["id"], new_owner_id)).fetchone()
    if not member or new_owner_id == user["id"]:
        flash("Choose another current team member as the new owner.", "error")
        return redirect(_team_url(team))
    # Update the owner row and membership roles as one database transaction.
    conn.execute("UPDATE teams SET owner_id=? WHERE id=?", (new_owner_id, team["id"]))
    conn.execute("UPDATE memberships SET role='member' WHERE team_id=? AND user_id=?", (team["id"], user["id"]))
    conn.execute("UPDATE memberships SET role='owner' WHERE team_id=? AND user_id=?", (team["id"], new_owner_id))
    conn.commit()
    flash("Team ownership transferred.", "success")
    return redirect(_team_url(team))


# Owners and administrators may delete a team; its designs remain published.
@app.route("/teams/<int:number>/delete", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/delete", methods=["POST"])
@login_required
def delete_team(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    user = current_user()
    if team["owner_id"] != user["id"] and not user["is_admin"]:
        abort(403)
    conn.execute("UPDATE designs SET team_id=NULL WHERE team_id=?", (team["id"],))
    conn.execute("DELETE FROM teams WHERE id=?", (team["id"],))
    conn.commit()
    delete_asset(UPLOAD_DIR, team["profile_image"])
    delete_asset(UPLOAD_DIR, team["banner_image"])
    flash(f"Team {number} was deleted. Its designs remain published as unaffiliated.", "success")
    return redirect(url_for("team_list"))


def send_team_membership_email(user, team, *, subject, heading, message, event_type):
    return email_service.send_email(
        to_email=user["email"], to_name=user["username"], subject=subject,
        heading=heading, message=message,
        action_url=url_for("notifications", _external=True),
        action_text="View notifications", event_type=event_type,
        team_number=team["number"], team_name=team["name"],
    )


@app.route("/teams/<int:number>/members/invite", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/members/invite", methods=["POST"])
@ratelimit.limit("team-invite", 30, 3600)
@login_required
def invite_team_member(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    if team["owner_id"] != current_user()["id"]:
        abort(403)
    username = (request.form.get("username") or "").strip()[:50]
    invitee = conn.execute(
        "SELECT * FROM users WHERE lower(username)=lower(?) AND deleted_at IS NULL",
        (username,),
    ).fetchone()
    if invitee is None:
        flash("No Botfolio user has that username.", "error")
    elif conn.execute(
        "SELECT 1 FROM memberships WHERE team_id=? AND user_id=?",
        (team["id"], invitee["id"]),
    ).fetchone():
        flash(f"{invitee['username']} is already on this team.", "error")
    elif conn.execute(
        """SELECT 1 FROM team_membership_requests
            WHERE team_id=? AND user_id=? AND status='pending'""",
        (team["id"], invitee["id"]),
    ).fetchone():
        flash("That user already has a pending invitation or join request.", "error")
    else:
        conn.execute(
            """INSERT INTO team_membership_requests
               (team_id,user_id,initiated_by_id,kind) VALUES (?,?,?,'invitation')""",
            (team["id"], invitee["id"], current_user()["id"]),
        )
        conn.commit()
        send_team_membership_email(
            invitee, team,
            subject=f"Team {number} invited you to join on Botfolio",
            heading=f"Invitation from Team {number}",
            message=(f"{current_user()['username']} invited you to join {team['name']}. "
                     "Accept or deny the invitation from your Botfolio notifications."),
            event_type="team_invitation",
        )
        flash(f"Invitation sent to {invitee['username']}.", "success")
    return redirect(_team_url(team))


@app.route("/teams/<int:number>/join-request", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/join-request", methods=["POST"])
@ratelimit.limit("team-join-request", 10, 3600)
@login_required
def request_team_membership(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    user = current_user()
    if conn.execute(
        "SELECT 1 FROM memberships WHERE team_id=? AND user_id=?",
        (team["id"], user["id"]),
    ).fetchone():
        flash("You are already a member of this team.", "error")
    elif conn.execute(
        """SELECT 1 FROM team_membership_requests
            WHERE team_id=? AND user_id=? AND status='pending'""",
        (team["id"], user["id"]),
    ).fetchone():
        flash("You already have a pending invitation or join request for this team.", "error")
    elif team["owner_id"] is None:
        flash("This team does not currently have an owner who can review requests.", "error")
    else:
        conn.execute(
            """INSERT INTO team_membership_requests
               (team_id,user_id,initiated_by_id,kind) VALUES (?,?,?,'request')""",
            (team["id"], user["id"], user["id"]),
        )
        owner = conn.execute("SELECT * FROM users WHERE id=?", (team["owner_id"],)).fetchone()
        conn.commit()
        send_team_membership_email(
            owner, team,
            subject=f"{user['username']} requested to join Team {number}",
            heading="New team join request",
            message=(f"{user['username']} asked to join {team['name']}. "
                     "Approve or deny the request from your Botfolio notifications."),
            event_type="team_join_request",
        )
        flash("Your join request was sent to the team owner.", "success")
    return redirect(_team_url(team))


@app.route("/team-membership-requests/<int:request_id>/respond", methods=["POST"])
@login_required
def respond_to_team_membership(request_id):
    action = request.form.get("action")
    if action not in {"accept", "deny"}:
        abort(400)
    conn = db.get_db()
    membership_request = conn.execute(
        """SELECT r.*,t.program,t.number,t.name,t.owner_id,u.username,u.email
             FROM team_membership_requests r JOIN teams t ON t.id=r.team_id
             JOIN users u ON u.id=r.user_id WHERE r.id=?""",
        (request_id,),
    ).fetchone()
    if membership_request is None:
        abort(404)
    user = current_user()
    can_respond = (
        membership_request["kind"] == "invitation" and membership_request["user_id"] == user["id"]
    ) or (
        membership_request["kind"] == "request" and membership_request["owner_id"] == user["id"]
    )
    if not can_respond:
        abort(403)
    if membership_request["status"] != "pending":
        flash("That team invitation or request has already been handled.", "error")
        return redirect(url_for("notifications"))
    status = "accepted" if action == "accept" else "denied"
    conn.execute(
        """UPDATE team_membership_requests SET status=?,responded_at=datetime('now')
            WHERE id=? AND status='pending'""",
        (status, request_id),
    )
    if action == "accept":
        conn.execute(
            "INSERT OR IGNORE INTO memberships(user_id,team_id) VALUES (?,?)",
            (membership_request["user_id"], membership_request["team_id"]),
        )
        # The legacy profile field is specifically an FTC affiliation. FRC
        # membership lives in the membership table and should not overwrite it.
        if membership_request["program"] == "ftc":
            conn.execute(
                "UPDATE users SET ftc_team_number=? WHERE id=? AND ftc_team_number IS NULL",
                (membership_request["number"], membership_request["user_id"]),
            )
    conn.commit()
    target = conn.execute("SELECT * FROM users WHERE id=?", (membership_request["user_id"],)).fetchone()
    team = {
        "program": membership_request["program"],
        "number": membership_request["number"],
        "name": membership_request["name"],
    }
    if membership_request["kind"] == "request":
        send_team_membership_email(
            target, team,
            subject=f"Your Team {team['number']} join request was {status}",
            heading=f"Join request {status}",
            message=(f"The owner of {team['name']} {status} your request to join the team."),
            event_type=f"team_request_{status}",
        )
    flash(f"Team membership {status}.", "success")
    return redirect(url_for("notifications"))


@app.route("/teams/<int:number>/members/<int:user_id>/remove", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/members/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_team_member(number, user_id, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)
    if team["owner_id"] != current_user()["id"] and not current_user()["is_admin"]:
        abort(403)
    if user_id == team["owner_id"]:
        abort(400)
    member = conn.execute(
        """SELECT u.* FROM memberships m JOIN users u ON u.id=m.user_id
            WHERE m.team_id=? AND m.user_id=?""",
        (team["id"], user_id),
    ).fetchone()
    if member is None:
        abort(404)
    conn.execute("DELETE FROM memberships WHERE team_id=? AND user_id=?", (team["id"], user_id))
    conn.execute(
        """UPDATE team_membership_requests SET status='cancelled',responded_at=datetime('now')
            WHERE team_id=? AND user_id=? AND status='pending'""",
        (team["id"], user_id),
    )
    conn.commit()
    send_team_membership_email(
        member, team,
        subject=f"You were removed from Team {number} on Botfolio",
        heading="Team membership removed",
        message=f"The owner of {team['name']} removed you from the team on Botfolio.",
        event_type="team_member_removed",
    )
    flash(f"{member['username']} was removed from Team {number}.", "success")
    return redirect(_team_url(team))


@app.route("/teams/<int:number>/join", defaults={"program": "ftc"}, methods=["POST"])
@app.route("/teams/<program>/<int:number>/join", methods=["POST"])
@login_required
def join_team(number, program):
    conn = db.get_db()
    program = _team_program(program)
    team = _find_team(conn, program, number) if program else None
    if team is None:
        abort(404)

    code = (request.form.get("invite_code") or "").strip()
    if not secrets.compare_digest(code, team["invite_code"]):
        flash("That invite code is not correct.", "error")
    else:
        user = current_user()
        cur = conn.execute(
            "INSERT OR IGNORE INTO memberships (user_id, team_id) VALUES (?, ?)",
            (user["id"], team["id"]),
        )
        conn.commit()
        if cur.rowcount:
            conn.execute(
                """UPDATE team_membership_requests SET status='cancelled',responded_at=datetime('now')
                    WHERE team_id=? AND user_id=? AND status='pending'""",
                (team["id"], user["id"]),
            )
            # Keep the older FTC-only profile field accurate without treating an
            # FRC membership as an FTC affiliation.
            if program == "ftc":
                conn.execute(
                    "UPDATE users SET ftc_team_number=? WHERE id=? AND ftc_team_number IS NULL",
                    (number, user["id"]),
                )
            conn.commit()
            email_service.send_email(
                to_email=user["email"],
                to_name=user["username"],
                subject=f"You joined Team {number} on Botfolio",
                heading=f"Welcome to Team {number}",
                message=(
                    f"Your Botfolio account is now connected to {team['name']}. "
                    "You can publish designs under this team and view its members."
                ),
                action_url=url_for("team_detail", program=program, number=number, _external=True),
                action_text="View team",
                event_type="team_joined",
                team_number=number,
                team_name=team["name"],
            )
            flash(f"You are now a member of team {number}.", "success")
        else:
            flash(f"You are already a member of team {number}.", "success")
    return redirect(_team_url(team))


# --------------------------------------------------------------------------
# AI feedback
# --------------------------------------------------------------------------

@app.route("/designs/<int:design_id>/grade", methods=["POST"])
# The only endpoint here that spends money: every call is an OpenAI request.
# This is the difference between a capped bill and an open one.
@ratelimit.limit("grade", 10, 3600)
@login_required
@verified_required
def grade_design(design_id):
    """Generate a private review that expires unless its requester saves it."""
    conn = db.get_db()
    design = conn.execute(
        """
        SELECT d.*, s.name AS season_name, a.name AS archetype_name,
               tm.number AS team_number
          FROM designs d
          LEFT JOIN seasons s ON s.id = d.season_id
          LEFT JOIN archetypes a ON a.id = d.archetype_id
          LEFT JOIN teams tm ON tm.id = d.team_id
         WHERE d.id = ?
        """,
        (design_id,),
    ).fetchone()
    if design is None:
        abort(404)
    # A hidden (moderated) design must not be gradable through a direct link:
    # that would spend the AI budget on it and leak its content back to the
    # requester as a saved review. Mirror the read-path visibility gate.
    if design["is_hidden"]:
        abort(404)

    if not openai_is_configured():
        flash("AI review is not configured on this server.", "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#feedback")

    daily_reviews = conn.execute(
        "SELECT COUNT(*) n FROM ai_feedback WHERE requester_id=? "
        "AND created_at>=datetime('now','-1 day')",
        (current_user()["id"],),
    ).fetchone()["n"]
    if daily_reviews >= 5:
        flash("You have reached the launch limit of 5 AI reviews per day.", "error")
        return redirect(url_for("design_detail", design_id=design_id) + "#feedback")

    question = (request.form.get("question") or "").strip()[:500]
    focus = (request.form.get("focus") or "Reliability").strip()
    allowed_focuses = {"Reliability", "Buildability", "Serviceability"}
    if focus not in allowed_focuses:
        focus = "Reliability"

    if not question:
        question = (
            f"Review this design for {focus.lower()}. What works well, "
            "what could fail, and what should be changed?"
        )

    try:
        image_data_url = None
        if design["image_filename"]:
            image_bytes = infra_storage.read("uploads", design["image_filename"])
            image_data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")
        review = review_design(
            title=design["title"],
            description=design["description"] or "No description was provided.",
            category=design["archetype_name"] or "Robot design",
            season=design["season_name"] or "Not provided",
            team_number=str(design["team_number"] or ""),
            focus=focus,
            question=question,
            image_data_url=image_data_url,
            safety_identifier=hashlib.sha256(
                f"botfolio-user:{current_user()['id']}".encode()
            ).hexdigest(),
        )

        rubric = {
            "summary": review["summary"],
            "answer": review["answer"],
            "focus": focus,
            "scores": {
                "overall": review["overall_score"],
                "reliability": review["reliability_score"],
                "buildability": review["buildability_score"],
                "serviceability": review["serviceability_score"],
            },
            "strengths": review["strengths"],
            "concerns": review["concerns"],
            "suggestions": review["suggestions"],
            "missing_information": review["missing_information"],
        }
        result = {
            "model": OPENAI_MODEL,
            "rubric": rubric,
            "summary": review["summary"],
            "status": "ok",
        }
    except ModerationRejected as exc:
        result = {"model": OPENAI_MODEL, "rubric": None, "summary": str(exc), "status": "error"}
    except Exception:
        app.logger.exception("OpenAI design review failed for design %s", design_id)
        result = {
            "model": OPENAI_MODEL,
            "rubric": None,
            "summary": "The AI review could not be completed. Please try again.",
            "status": "error",
        }

    # Save both successful and failed attempts so reloading the page never
    # causes another API request automatically.
    conn.execute(
        "INSERT INTO ai_feedback (design_id, requester_id, question, model, rubric_json, summary, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            design_id,
            current_user()["id"],
            question,
            result["model"],
            json.dumps(result["rubric"]) if result["rubric"] else "",
            result["summary"],
            result["status"],
        ),
    )
    conn.commit()

    if result["status"] == "ok":
        flash("AI feedback generated.", "success")
    else:
        flash(result["summary"], "error")
    return redirect(url_for("design_detail", design_id=design_id) + "#feedback")


@app.route("/ai-chats/<int:feedback_id>/save", methods=["POST"])
@login_required
def toggle_ai_chat_saved(feedback_id):
    """Save or unsave an AI chat; only its requester may change it."""
    conn = db.get_db()
    feedback = conn.execute(
        "SELECT * FROM ai_feedback WHERE id=? AND requester_id=?",
        (feedback_id, current_user()["id"]),
    ).fetchone()
    if feedback is None:
        abort(404)
    saving = feedback["saved_at"] is None
    conn.execute(
        "UPDATE ai_feedback SET saved_at="
        + ("datetime('now')" if saving else "NULL")
        + " WHERE id=?",
        (feedback_id,),
    )
    conn.commit()
    flash("AI chat saved to your profile." if saving else "AI chat removed from saved chats.", "success")
    if request.form.get("next") == "profile":
        return redirect(url_for("profile", username=current_user()["username"]) + "#ai-chats")
    return redirect(url_for("design_detail", design_id=feedback["design_id"]) + "#feedback")


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403,
                           message="That isn't yours to change."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404,
                           message="No such page."), 404


@app.errorhandler(500)
def internal_error(_):
    return render_template(
        "error.html", code=500,
        message="Something went wrong. Please try again, or contact support if the problem continues.",
    ), 500


@app.errorhandler(413)
def too_large(_):
    return render_template(
        "error.html", code=413,
        message="That form submission was too large. Images must be under 8 MB. "
                "Production model uploads use the separate direct uploader and "
                "may be up to 2.5 GB.",
    ), 413


def _network_address():
    """This machine's address on the LAN, or None if it is not on one.

    app.run binds 0.0.0.0, so the site is already reachable from a phone on the
    same wifi — but only if you know which address to type, and that is not
    something the loopback address tells you. Opening a UDP socket toward a
    public address makes the OS pick the interface it would route through; no
    packet is actually sent, and nothing has to be reachable for it to work.
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def _startup_banner(port):
    """What is running, where to reach it, and how to stop it.

    Printed rather than logged: this is addressed to the person who just typed
    `python app.py`, so it should look the same whatever LOG_JSON is set to.
    ASCII only, because a piped stdout on Windows falls back to the console
    codepage and box-drawing characters would raise UnicodeEncodeError there.
    """
    line = "=" * 64
    rows = [("On this computer", f"http://localhost:{port}")]

    address = _network_address()
    if address:
        rows.append(("On your wifi", f"http://{address}:{port}"))

    if db.using_postgres():
        rows.append(("Database", "Postgres"))
    else:
        try:
            conn = db.connect()
            designs = conn.execute("SELECT COUNT(*) AS n FROM designs").fetchone()["n"]
            conn.close()
            rows.append(("Database", f"{db.DB_PATH.name} ({designs} designs)"))
        except Exception:
            # A banner must never be the reason the app fails to start.
            rows.append(("Database", db.DB_PATH.name))

    rows.append(("Uploads", settings.describe()["uploads"] if settings.uses_s3
                 else "static/uploads (this computer)"))
    # Ask the service rather than reading the variable here, so the banner
    # cannot drift from what the feature itself checks.
    rows.append(("AI feedback", "on" if openai_is_configured() else
                 "off (no OPENAI_API_KEY in the environment)"))

    print(f"\n{line}\n  Botfolio is running\n{line}\n")
    for label, value in rows:
        print(f"  {label:<18}{value}")
    print("\n  Press Ctrl+C to stop. Saving a file restarts it automatically.")
    print(f"{line}\n")


if __name__ == "__main__":
    if not db.db_is_initialized():
        print("No database found. Run `python seed.py` first.")
    # The reloader runs this file twice: once in the parent that watches for
    # edits, once in the child that serves. Only the parent should print, or
    # the banner reappears on every save.
    elif not os.environ.get("WERKZEUG_RUN_MAIN"):
        _startup_banner(int(os.getenv("PORT", 8080)))
    # Pick up edits without a manual restart. Both halves are needed: the
    # reloader restarts on .py changes, auto-reload re-reads templates. With
    # only one, a template can compile against an app that has not caught up
    # and the page 500s on a filter that "does not exist" yet.
    #
    # Deliberately not debug=True: that also serves Werkzeug's interactive
    # console, and this binds every interface, so anyone on the network would
    # reach it. Set FLASK_DEBUG=1 for a session when you actually need it.
    # Setting TEMPLATES_AUTO_RELOAD here would be too late to matter:
    # registering the tagcase filter above touches app.jinja_env, and building
    # that environment is what reads the config. Assign to the live environment
    # instead, which works whenever it was created.
    app.jinja_env.auto_reload = True
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)), use_reloader=True)
