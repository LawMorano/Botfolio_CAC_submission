"""The Academy's first curriculum slice. No learner state is stored here."""

import re

LEVELS = (
    "Start Here",
    "CAD Foundations",
    "FTC-Ready CAD",
    "Mechanism Labs",
    "Robot Integration and Strategy",
)
DIFFICULTIES = frozenset({"Beginner", "Intermediate", "Advanced"})
STATUSES = frozenset({"Live", "Planned"})

PATHWAYS = {
    "onshape": {
        "name": "Onshape",
        "description": "Build together in a browser with Part Studios, variables, and mates.",
        "logo": "images/onshape-logo.png",
        "other": "fusion-360",
    },
    "fusion-360": {
        "name": "Fusion 360",
        "description": "Build parametric components with sketches, user parameters, and joints.",
        "logo": "images/fusion-360-logo.png",
        "other": "onshape",
    },
}

ENGINEERING_BRIEF = (
    "Design a compact, serviceable parallel-plate drivetrain for an FTC robot. "
    "Your CAD should make wheel placement, bearing support, motor mounting, and "
    "assembly clearance easy to inspect before any part is fabricated."
)
OBJECTIVES = (
    "Translate a robot envelope into a parameter-driven layout.",
    "Model two matching plates with serviceable wheel and motor interfaces.",
    "Constrain moving and fixed parts, then inspect fit and motion.",
    "Explain design choices with evidence in a portfolio artifact.",
)
CONSTRAINTS = (
    "Keep the complete drivetrain inside the team's current FTC robot size envelope; verify the current season rules before building.",
    "Allow clearance for wheels, fasteners, bearings, motors, wiring, and assembly tools.",
    "Use dimensions from the actual components your team selects; placeholder dimensions must be marked for later verification.",
    "Show a plausible way to manufacture, assemble, and replace a damaged plate.",
)
CHECKPOINTS = (
    "The envelope and centerlines have named dimensions; changing track width updates both sides.",
    "The plates remain symmetric and mounting holes align after a parameter change.",
    "A section or interference review shows free wheel rotation and accessible fasteners.",
)
CHALLENGE = (
    "Revise your drivetrain for a wider wheel while keeping its outer envelope fixed. "
    "Show what moved, what clearance became tighter, and why your final spacing is defensible."
)
ARTIFACTS = (
    "A view of the complete assembly and one plate with dimensions or annotations.",
    "A short parameter table listing envelope, track width, wheel diameter, and plate spacing.",
    "A clearance or motion check and a note explaining one issue you found and fixed.",
    "A brief reflection on manufacturing, service access, and the wider-wheel revision.",
)
RUBRIC = (
    {"criterion": "Envelope and parameters", "evidence": "Named dimensions drive a symmetric layout inside the stated envelope."},
    {"criterion": "Interfaces and assembly", "evidence": "Plate features align with selected hardware and fixed and moving parts are constrained sensibly."},
    {"criterion": "Verification", "evidence": "Clearance, motion, and service access are checked and one revision is explained."},
    {"criterion": "Communication", "evidence": "The published artifact lets another builder understand dimensions, choices, and remaining assumptions."},
)

LESSON_TITLES = (
    "Establish the design brief and robot envelope",
    "Create the master layout sketch",
    "Model the two drivetrain plates",
    "Add wheel, bearing, shaft, and motor interfaces",
    "Assemble, constrain, inspect, and review the drivetrain",
)

SHARED_LESSONS = (
    {"id": "brief", "title": LESSON_TITLES[0], "concept": "List your chosen wheels and motors, draw the maximum envelope, and record the source of each hardware dimension.", "checkpoint": CHECKPOINTS[0], "troubleshooting": "If a dimension is unknown, label it provisional and leave room to replace it with a measured value."},
    {"id": "layout", "title": LESSON_TITLES[1], "concept": "Place wheel centerlines and motor axes around the robot center. Drive mirrored positions from named dimensions rather than independent guesses.", "checkpoint": CHECKPOINTS[0], "troubleshooting": "If one side drifts when track width changes, replace duplicated dimensions with a mirrored relationship."},
    {"id": "plates", "title": LESSON_TITLES[2], "concept": "Create two plates from the layout. Leave material around fasteners and bearings, and provide a practical path to cut or machine each plate.", "checkpoint": CHECKPOINTS[1], "troubleshooting": "If holes no longer align, check whether both plates reference the same master layout."},
    {"id": "interfaces", "title": LESSON_TITLES[3], "concept": "Add wheel, bearing, shaft, and motor interfaces using manufacturer dimensions. Check access for fasteners and a removable wheel or motor.", "checkpoint": CHECKPOINTS[1], "troubleshooting": "If a bearing or motor floats in empty space, inspect the support path back to a plate."},
    {"id": "assembly", "title": LESSON_TITLES[4], "concept": "Bring the drivetrain together, lock fixed hardware, allow wheels to rotate, and inspect collisions and service access.", "checkpoint": CHECKPOINTS[2], "troubleshooting": "If every part moves together or nothing moves, inspect which constraints are fixed and which permit rotation."},
)

EDITION_STEPS = {
    "onshape": (
        "Start a document and record the envelope and hardware assumptions in a note. Set up a Part Studio for the drivetrain.",
        "Create a master sketch in the Part Studio. Use variables for track width, plate spacing, and wheel diameter; mirror wheel centers about the origin.",
        "Use multi-part design in the Part Studio to make left and right plates from shared geometry. Verify both parts respond to a variable edit.",
        "Place or model simplified wheel, bearing, shaft, and motor parts. Add mate connectors at their actual axes and check mounting-hole locations.",
        "Insert parts into an Assembly. Use Fastened mates for fixed hardware and Revolute mates for wheels; inspect motion and interference.",
    ),
    "fusion-360": (
        "Create a design and note the envelope and hardware assumptions. Set up separate components for the drivetrain.",
        "Create a master sketch. Use user parameters for track width, plate spacing, and wheel diameter; mirror wheel centers about the origin.",
        "Build each plate as a component from shared sketch geometry rather than leaving separate unorganized bodies. Verify both update after a parameter edit.",
        "Add simplified wheel, bearing, shaft, and motor components. Place joint origins on their actual axes and check mounting-hole locations.",
        "Use rigid joints or groups for fixed hardware and revolute joints for wheels. Inspect motion, interference, and service access.",
    ),
}

PLANNED = (
    ("quick-start-cad-mental-model", "Quick Start and CAD Mental Model", "Start Here", "Beginner", 45, "Understand sketches, features, and design intent.", ("Navigation", "Design intent")),
    ("sketching-and-parameters", "Sketching and Parameters/Variables", "CAD Foundations", "Beginner", 75, "Make stable sketches and editable dimensions.", ("Sketch constraints", "Parameters")),
    ("parts-components-ftc-libraries", "Parts or Components and FTC Libraries", "FTC-Ready CAD", "Intermediate", 90, "Organize parts and use verified FTC hardware dimensions.", ("Part organization", "Hardware libraries")),
    ("assemblies-and-motion", "Assemblies and Motion", "FTC-Ready CAD", "Intermediate", 90, "Constrain a mechanism and inspect its motion.", ("Assembly", "Motion checks")),
)

NEXT_COURSE = (
    "robot-integration-strategy", "Robot Integration and Strategy",
    "Robot Integration and Strategy", "Advanced", 120,
    "Fit a proven drivetrain into a complete robot layout and defend subsystem tradeoffs.",
    ("Subsystem integration", "Design tradeoffs"),
)


def _planned_course(platform, item):
    slug, title, level, difficulty, duration, summary, skills = item
    return {
        "slug": slug, "platform": platform, "title": title, "summary": summary,
        "level": level, "difficulty": difficulty, "duration_minutes": duration,
        "status": "Planned", "outcome": summary, "prerequisites": (),
        "skills": skills, "tools": (PATHWAYS[platform]["name"],), "lessons": (),
        "checkpoints": (), "challenge": "Coming next", "artifacts": (), "rubric": (),
        "related": (), "equivalent_slug": slug,
    }


def _pilot_course(platform):
    lessons = tuple({**shared, "step": step} for shared, step in zip(SHARED_LESSONS, EDITION_STEPS[platform]))
    return {
        "slug": "parallel-plate-drivetrain", "platform": platform,
        "title": "Parallel-Plate Drivetrain", "summary": "Design, assemble, and review a serviceable FTC drivetrain.",
        "level": "Mechanism Labs", "difficulty": "Intermediate", "duration_minutes": 180,
        "status": "Live", "outcome": "A parameter-driven, reviewed drivetrain assembly and a portfolio-ready design explanation.",
        "prerequisites": ("Basic sketching", "Parts or components", "Assembly constraints"),
        "skills": ("Parametric layout", "Hardware interfaces", "Motion and clearance review", "Design communication"),
        "tools": (PATHWAYS[platform]["name"], "Chosen FTC wheel, bearing, shaft, and motor specifications"),
        "lessons": lessons, "brief": ENGINEERING_BRIEF, "objectives": OBJECTIVES,
        "constraints": CONSTRAINTS, "checkpoints": CHECKPOINTS, "challenge": CHALLENGE,
        "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "related": ("robot-integration-strategy",), "equivalent_slug": "parallel-plate-drivetrain",
    }


CATALOG = {
    platform: tuple([*(_planned_course(platform, item) for item in PLANNED),
                     _pilot_course(platform), _planned_course(platform, NEXT_COURSE)])
    for platform in PATHWAYS
}


def validate_catalog(catalog=CATALOG):
    """Raise ValueError for malformed curriculum data, including broken edition links."""
    required = {"slug", "platform", "title", "summary", "level", "difficulty", "duration_minutes",
                "status", "outcome", "prerequisites", "skills", "tools", "lessons", "checkpoints",
                "challenge", "artifacts", "rubric", "related", "equivalent_slug"}
    for platform, courses in catalog.items():
        if platform not in PATHWAYS:
            raise ValueError(f"Unsupported platform: {platform}")
        seen = set()
        for course in courses:
            missing = required - course.keys()
            if missing or any(course.get(key) in (None, "") for key in required):
                raise ValueError(f"Missing required course fields: {sorted(missing)}")
            if not isinstance(course["platform"], str) or course["platform"] != platform or course["platform"] not in PATHWAYS:
                raise ValueError("Unsupported or mismatched course platform")
            if not isinstance(course["slug"], str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", course["slug"]):
                raise ValueError("Course needs a stable slug")
            if course["slug"] in seen:
                raise ValueError("Duplicate course slug")
            seen.add(course["slug"])
            if not isinstance(course["duration_minutes"], (int, float)) or course["duration_minutes"] < 0:
                raise ValueError("Invalid course duration")
            if not isinstance(course["status"], str) or not isinstance(course["difficulty"], str) or course["status"] not in STATUSES or course["difficulty"] not in DIFFICULTIES:
                raise ValueError("Invalid course status or difficulty")
            if not isinstance(course["level"], str) or course["level"] not in LEVELS:
                raise ValueError("Invalid course level")
            if not isinstance(course["lessons"], (list, tuple)):
                raise ValueError("Lessons must be an ordered collection")
            lesson_ids = set()
            for lesson in course["lessons"]:
                if (not isinstance(lesson, dict)
                        or not isinstance(lesson.get("id"), str) or not lesson["id"].strip()
                        or not isinstance(lesson.get("title"), str) or not lesson["title"].strip()
                        or lesson["id"] in lesson_ids):
                    raise ValueError("Lessons need unique stable IDs and titles")
                lesson_ids.add(lesson["id"])
    for platform, courses in catalog.items():
        other = PATHWAYS[platform]["other"]
        for course in courses:
            equivalent = course["equivalent_slug"]
            if equivalent and other in catalog and not any(c["slug"] == equivalent for c in catalog[other]):
                raise ValueError("Missing equivalent course")
    return True


validate_catalog()


def get_course(platform, slug):
    return next((course for course in CATALOG.get(platform, ()) if course["slug"] == slug), None)
