"""Create the database and fill it with demo content.

    python seed.py

Destroys and rebuilds designhub.db, then writes a few demo designs — including
real .stl files and preview renders — so a fresh clone has something to look at
before anyone uploads anything.

The demo geometry is generated here rather than committed as binary blobs, and
the preview images are produced by a small software renderer below (seeding
cannot use the browser's WebGL viewer that real submissions go through).
"""

import json
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw
from werkzeug.security import generate_password_hash

import db

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
MODEL_DIR = BASE_DIR / "static" / "models"

DEMO_PASSWORD = "designhub123"

RENDER_SIZE = (1024, 768)
BACKGROUND = (19, 24, 32)


# --------------------------------------------------------------------------
# Tiny mesh builders
# --------------------------------------------------------------------------

def box(x0, y0, z0, x1, y1, z1):
    """Triangles for an axis-aligned box, wound counter-clockwise outwards."""
    quads = [
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],   # +X
        [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],   # -X
        [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],   # +Y
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],   # -Y
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],   # +Z
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],   # -Z
    ]
    tris = []
    for a, b, c, d in quads:
        tris.append((a, b, c))
        tris.append((a, c, d))
    return tris


def tube(x0, y0, z0, x1, y1, z1, wall):
    """A hollow rectangular extrusion along Z — the classic FTC boxtube."""
    tris = []
    tris += box(x0, y0, z0, x1, y0 + wall, z1)            # bottom wall
    tris += box(x0, y1 - wall, z0, x1, y1, z1)            # top wall
    tris += box(x0, y0 + wall, z0, x0 + wall, y1 - wall, z1)   # left wall
    tris += box(x1 - wall, y0 + wall, z0, x1, y1 - wall, z1)   # right wall
    return tris


def cylinder(cx, cy, z0, z1, radius, segments=24):
    """A capped cylinder whose axis runs along Z."""
    tris = []
    ring = [
        (cx + radius * math.cos(2 * math.pi * i / segments),
         cy + radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]
    for i in range(segments):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % segments]
        tris.append(((ax, ay, z0), (bx, by, z0), (bx, by, z1)))
        tris.append(((ax, ay, z0), (bx, by, z1), (ax, ay, z1)))
        tris.append(((cx, cy, z1), (ax, ay, z1), (bx, by, z1)))     # top cap
        tris.append(((cx, cy, z0), (bx, by, z0), (ax, ay, z0)))     # bottom cap
    return tris


# --------------------------------------------------------------------------
# Binary STL output
# --------------------------------------------------------------------------

def normal_of(tri):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / length, ny / length, nz / length


def write_stl(path, triangles, name="ftc-design-hub"):
    with open(path, "wb") as f:
        f.write(name.encode("ascii", "replace").ljust(80, b"\0")[:80])
        f.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            f.write(struct.pack("<3f", *normal_of(tri)))
            for vertex in tri:
                f.write(struct.pack("<3f", *vertex))
            f.write(struct.pack("<H", 0))


# --------------------------------------------------------------------------
# Software renderer for the seeded previews
# --------------------------------------------------------------------------

def _rotate(v, yaw, pitch):
    x, y, z = v
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy - z * sy, x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    return x, y, z


def render(triangles, path, yaw=0.9, pitch=0.5):
    """Flat-shaded orthographic render: cull backfaces, then painter's algorithm."""
    view = [tuple(_rotate(v, yaw, pitch) for v in tri) for tri in triangles]

    xs = [v[0] for tri in view for v in tri]
    ys = [v[1] for tri in view for v in tri]
    width, height = RENDER_SIZE
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = min(width, height) * 0.78 / span
    ox = width / 2 - (min(xs) + max(xs)) / 2 * scale
    oy = height / 2 + (min(ys) + max(ys)) / 2 * scale

    light = (-0.35, 0.6, 0.72)
    faces = []
    for tri in view:
        nx, ny, nz = normal_of(tri)
        if nz <= 0:
            continue  # facing away from the camera
        shade = max(0.0, nx * light[0] + ny * light[1] + nz * light[2])
        tone = 0.22 + 0.78 * shade ** 0.8
        colour = (int(214 * tone) + 18, int(220 * tone) + 20, int(232 * tone) + 22)
        depth = sum(v[2] for v in tri) / 3
        points = [(ox + v[0] * scale, oy - v[1] * scale) for v in tri]
        faces.append((depth, points, colour))

    faces.sort(key=lambda f: f[0])  # far to near

    image = Image.new("RGB", RENDER_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    for _, points, colour in faces:
        draw.polygon(points, fill=colour, outline=(12, 16, 22))

    image.save(path, format="JPEG", quality=88)


def camera_for(yaw, pitch, distance=3.5):
    """The viewer camera matching a `render()` angle.

    A real submission gets its preview and its camera from the same moment in
    the browser, so they always agree. Seeded designs have to reproduce that:
    `render()` turns the model by yaw then pitch and looks down -Z, so the
    equivalent camera sits at the inverse rotation of (0, 0, distance).
    viewer.js normalises every model to a bounding sphere of radius 1, which is
    why one fixed distance works for all of them.
    """
    return json.dumps({
        "position": [
            round(distance * math.cos(pitch) * math.sin(yaw), 4),
            round(distance * math.sin(pitch), 4),
            round(distance * math.cos(pitch) * math.cos(yaw), 4),
        ],
        "target": [0.0, 0.0, 0.0],
    })


def placeholder(path, title, subtitle):
    """A plain preview for the demo design that has no 3D model."""
    image = Image.new("RGB", RENDER_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    w, h = RENDER_SIZE
    for i in range(0, w, 48):
        draw.line([(i, 0), (i, h)], fill=(26, 32, 42))
    for i in range(0, h, 48):
        draw.line([(0, i), (w, i)], fill=(26, 32, 42))
    draw.rectangle([w * 0.12, h * 0.28, w * 0.88, h * 0.72],
                   outline=(255, 122, 61), width=3)
    draw.text((w * 0.16, h * 0.42), title, fill=(230, 237, 243))
    draw.text((w * 0.16, h * 0.50), subtitle, fill=(139, 151, 167))
    image.save(path, format="JPEG", quality=88)


# --------------------------------------------------------------------------
# Demo content
# --------------------------------------------------------------------------

SEASONS = [
    # Edit these freely — they're only seed data.
    ("DECODE",         "2025-26", "decode",         4),
    ("INTO THE DEEP",  "2024-25", "into-the-deep",  3),
    ("CENTERSTAGE",    "2023-24", "centerstage",    2),
    ("POWERPLAY",      "2022-23", "powerplay",      1),
]

# Season-specific archetypes: a robot's role and how it scores. These are the
# INTO THE DEEP ones; new ones get coined from the submit form.
SEASON_ARCHETYPES = {
    "into-the-deep": [
        ("Spec passthrough w/ rails", "spec-passthrough-w-rails",
         "Takes specimens in at one end and passes them through to a scoring "
         "position on rails, without re-grabbing."),
        ("Boxtube", "boxtube",
         "Built around telescoping box tube extension for reach and lift."),
        ("Auto-clipper", "auto-clipper",
         "Optimised to clip specimens onto the chamber quickly, usually with a "
         "heavy autonomous scoring routine."),
    ],
}

# Cross-season mechanisms — real design patterns that outlive any one game, so
# they get a NULL season and show up whatever season you pick.
GENERAL_ARCHETYPES = [
    ("Virtual four-bar", "virtual-four-bar",
     "Two linked servos keeping an intake level through its arc."),
    ("Linear slide lift", "linear-slide-lift",
     "Vertical extension on linear slides."),
    ("Mecanum drive", "mecanum-drive", "Holonomic drivetrain on mecanum wheels."),
    ("Swerve drive", "swerve-drive", "Independently steered and driven modules."),
]


def build_demo_models():
    """Return [(model_filename, image_filename, mesh_builder)] after writing files."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Two-stage boxtube slide.
    slide = []
    slide += tube(-22, -22, 0, 22, 22, 300, 4)
    slide += tube(-16, -16, 210, 16, 16, 500, 3.5)
    slide += box(-30, -30, -8, 30, 30, 0)                    # mounting plate
    slide += cylinder(0, 0, 500, 512, 14, 20)                # pulley at the top

    # 2. Virtual four-bar intake: a roller on two arms, plus a cross brace.
    intake = []
    for side in (-70, 70):                                   # the two arms
        intake += box(side, -6, -150, side + 10, 6, 0)
        intake += box(side, -6, -150, side + 10, 45, -140)   # elbow at the pivot
    intake += box(-80, -32, -150, 80, -22, -140)             # cross brace
    # The roller spans the gap between the arms, so build it along Z and lay it
    # down onto X by swapping those two coordinates. Swapping two axes mirrors
    # the mesh, which flips every normal inward — reversing the vertex order of
    # each triangle winds them back outwards.
    roller = cylinder(0, 0, -70, 70, 22, 24)
    intake += [tuple((v[2], v[1], v[0]) for v in reversed(tri)) for tri in roller]

    # Angles chosen to sit well away from the viewer's default three-quarter
    # view, so opening "View in 3D" on a demo design visibly lands on the angle
    # its preview was framed at rather than looking like a coincidence.
    jobs = [
        ("boxtube-slide.stl", "demo-boxtube-slide.jpg", slide, 2.25, 0.95),
        ("virtual-four-bar.stl", "demo-virtual-four-bar.jpg", intake, -0.75, -0.45),
    ]
    cameras = {}
    for model_name, image_name, mesh, yaw, pitch in jobs:
        write_stl(MODEL_DIR / model_name, mesh)
        render(mesh, UPLOAD_DIR / image_name, yaw=yaw, pitch=pitch)
        cameras[image_name] = camera_for(yaw, pitch)

    placeholder(UPLOAD_DIR / "demo-auto-clipper.jpg",
                "Auto-clipper specimen scorer",
                "photo upload — no 3D model attached")

    return cameras


def main():
    print("Rebuilding the database…")
    db.init_db()
    conn = db.connect()

    # --- users -----------------------------------------------------------
    users = {}
    for username, email, role in [("rahul", "rahul@example.com", "student"),
                                  ("mentor_kim", "kim@example.com", "mentor"),
                                  ("team_9999", "team@example.com", "coach")]:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, bio, ftc_role) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, email, generate_password_hash(DEMO_PASSWORD),
             "Demo account created by seed.py.", role),
        )
        users[username] = cur.lastrowid

    # --- seasons and archetypes ------------------------------------------
    seasons = {}
    for name, year_label, slug, order in SEASONS:
        cur = conn.execute(
            "INSERT INTO seasons (name, year_label, slug, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (name, year_label, slug, order),
        )
        seasons[slug] = cur.lastrowid

    archetypes = {}
    for season_slug, entries in SEASON_ARCHETYPES.items():
        for name, slug, description in entries:
            cur = conn.execute(
                "INSERT INTO archetypes (season_id, name, slug, description) "
                "VALUES (?, ?, ?, ?)",
                (seasons[season_slug], name, slug, description),
            )
            archetypes[slug] = cur.lastrowid

    for name, slug, description in GENERAL_ARCHETYPES:
        cur = conn.execute(
            "INSERT INTO archetypes (season_id, name, slug, description) "
            "VALUES (NULL, ?, ?, ?)",
            (name, slug, description),
        )
        archetypes[slug] = cur.lastrowid

    # --- a team ----------------------------------------------------------
    cur = conn.execute(
        "INSERT INTO teams (number, name, region, owner_id, invite_code, is_founding) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (9999, "Demo Robotics", "Demo League", users["team_9999"], "demo-invite"),
    )
    team_id = cur.lastrowid
    conn.execute(
        "INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, 'owner')",
        (users["team_9999"], team_id),
    )

    # --- demo designs ----------------------------------------------------
    print("Generating demo geometry and previews…")
    cameras = build_demo_models()

    designs = [
        {
            "user": "rahul", "team": team_id,
            "title": "Two-stage boxtube slide",
            "description": (
                "Two-stage telescoping boxtube on a 30x30 mounting plate, driven "
                "by a single string run over the pulley at the top. Roughly 500mm "
                "of extension from a 300mm retracted stack.\n\n"
                "Stage tolerances are tight enough that it needs shimming if the "
                "print warps. Would go to a cascading rig next time."
            ),
            "season": "into-the-deep", "archetype": "boxtube",
            "image": "demo-boxtube-slide.jpg", "model": "boxtube-slide.stl",
            "tags": ["boxtube", "linear slide", "3d printed", "two stage"],
        },
        {
            "user": "mentor_kim", "team": None,
            "title": "Virtual four-bar intake",
            "description": (
                "Compliant roller on a virtual four-bar so the intake stays level "
                "through the whole arc. Arms are 150mm; the roller is a 22mm "
                "compliant wheel stack on a dead axle.\n\n"
                "Simple, cheap, and very hard to jam. The cross brace matters more "
                "than it looks — without it the arms splay under load."
            ),
            "season": "into-the-deep", "archetype": "virtual-four-bar",
            "image": "demo-virtual-four-bar.jpg", "model": "virtual-four-bar.stl",
            "tags": ["intake", "virtual four bar", "compliant wheels"],
        },
        {
            "user": "team_9999", "team": team_id,
            "title": "Auto-clipper specimen scorer",
            "description": (
                "Photo-only entry, to show that a design without a CAD file works "
                "the same as one with it. Clips specimens onto the high chamber "
                "with a fixed-height claw, tuned for a fast autonomous cycle."
            ),
            "season": "into-the-deep", "archetype": "auto-clipper",
            "image": "demo-auto-clipper.jpg", "model": None,
            "tags": ["specimen", "autonomous", "claw"],
        },
    ]

    design_ids = {}
    for spec in designs:
        cur = conn.execute(
            """
            INSERT INTO designs (user_id, team_id, title, description, onshape_link, season_id,
                                 prototype_version, competition_tested,
                                 length_in, width_in, height_in, motor_count, servo_count,
                                 archetype_id, image_filename, model_filename,
                                 camera_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (users[spec["user"]], spec["team"], spec["title"], spec["description"],
             spec.get("onshape"),
             seasons[spec["season"]], spec.get("prototype_version", 1),
             spec.get("competition_tested", 0), spec.get("length_in", 12),
             spec.get("width_in", 12), spec.get("height_in", 12),
             spec.get("motor_count"), spec.get("servo_count"),
             archetypes[spec["archetype"]],
             # The camera comes from the same angle the preview was rendered
             # at, so the two always agree — see camera_for().
             spec["image"], spec["model"], cameras.get(spec["image"])),
        )
        design_id = cur.lastrowid
        design_ids[spec["title"]] = design_id

        for position, filename in enumerate(spec.get("images", [spec["image"]])):
            conn.execute(
                "INSERT INTO design_images(design_id,filename,position) VALUES(?,?,?)",
                (design_id, filename, position),
            )

        for tag_name in spec["tags"]:
            row = conn.execute(
                "SELECT id FROM tags WHERE name = ?", (tag_name,)
            ).fetchone()
            if row is None:
                tag_cur = conn.execute(
                    "INSERT INTO tags (name, created_by) VALUES (?, ?)",
                    (tag_name, users[spec["user"]]),
                )
                tag_id = tag_cur.lastrowid
            else:
                tag_id = row["id"]
            conn.execute(
                "INSERT OR IGNORE INTO design_tags (design_id, tag_id, added_by) "
                "VALUES (?, ?, ?)",
                (design_id, tag_id, users[spec["user"]]),
            )

    # --- votes, including one tag voted far enough down to be buried ------
    slide_id = design_ids["Two-stage boxtube slide"]

    # A wrong tag, added by someone else and then voted down by two people.
    wrong = conn.execute(
        "INSERT INTO tags (name, created_by) VALUES ('swerve', ?)",
        (users["mentor_kim"],),
    ).lastrowid
    conn.execute(
        "INSERT INTO design_tags (design_id, tag_id, added_by) VALUES (?, ?, ?)",
        (slide_id, wrong, users["mentor_kim"]),
    )
    for voter in ("rahul", "team_9999"):
        conn.execute(
            "INSERT INTO tag_votes (user_id, design_id, tag_id, value) "
            "VALUES (?, ?, ?, -1)",
            (users[voter], slide_id, wrong),
        )

    # And some upvotes on the accurate ones.
    for tag_name in ("boxtube", "linear slide"):
        tag_id = conn.execute(
            "SELECT id FROM tags WHERE name = ?", (tag_name,)
        ).fetchone()["id"]
        for voter in ("mentor_kim", "team_9999"):
            conn.execute(
                "INSERT INTO tag_votes (user_id, design_id, tag_id, value) "
                "VALUES (?, ?, ?, 1)",
                (users[voter], slide_id, tag_id),
            )

    conn.commit()

    counts = {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("users", "teams", "seasons", "archetypes", "designs",
                      "design_images", "tags", "design_tags", "tag_votes",
                      "design_likes", "design_visits", "comments")
    }
    conn.close()

    print("\nDone. " + ", ".join(f"{n} {t}" for t, n in counts.items()))
    print(f"\nDemo accounts (password: {DEMO_PASSWORD})")
    for username in ("rahul", "mentor_kim", "team_9999"):
        print(f"  {username}")
    print("\nTeam 9999 invite code: demo-invite")
    print("\nNow run:  flask --app app run")


if __name__ == "__main__":
    main()
