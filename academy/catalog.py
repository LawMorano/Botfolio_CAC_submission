"""Academy indexes, lookups, and curriculum validation."""

import re

from academy.content.parallel_plate import ENGINEERING_BRIEF, OBJECTIVES, RUBRIC, build_course as build_parallel_plate
from academy.content.quick_start import build_course as build_quick_start

LEVELS = ("Start Here", "Mechanism Labs")
DIFFICULTIES = frozenset({"Beginner", "Intermediate", "Advanced"})
STATUSES = frozenset({"Live", "Planned"})

PATHWAYS = {
    "onshape": {"name": "Onshape", "description": "Build together in a browser with Part Studios, variables, and mates.", "logo": "images/onshape-logo.png", "other": "fusion-360"},
    "fusion-360": {"name": "Fusion 360", "description": "Build parametric components with sketches, user parameters, and joints.", "logo": "images/fusion-360-logo.png", "other": "onshape"},
}

PLANNED = (
    ("robot-integration-strategy", "Robot Integration and Strategy", "Robot Integration and Strategy", "Advanced", 120, "Fit a proven drivetrain into a complete robot layout and defend subsystem tradeoffs.", ("Subsystem integration", "Design tradeoffs")),
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


CATALOG = {
    platform: (
        build_quick_start(platform, pathway["name"]),
        build_parallel_plate(platform, pathway["name"]),
    )
    for platform, pathway in PATHWAYS.items()
}

COURSE_REQUIRED = {"slug", "platform", "title", "summary", "level", "difficulty", "duration_minutes", "status", "outcome", "prerequisites", "skills", "tools", "lessons", "checkpoints", "challenge", "artifacts", "rubric", "related", "equivalent_slug"}
LESSON_REQUIRED = {"id", "title", "summary", "estimated_minutes", "outcome", "ftc_relevance", "concepts", "required_setup", "steps", "checkpoints", "common_mistakes", "practice", "completion_checklist", "self_check"}
STEP_REQUIRED = {"title", "action", "reason", "result"}
SELF_CHECK_REQUIRED = {"question", "answer"}
FOREIGN_TERMS = {
    "onshape": ("user parameter", "joint origin", "rigid joint", "feature timeline"),
    "fusion-360": ("part studio", "mate connector", "fastened mate"),
}


def _has_text(value):
    return isinstance(value, str) and bool(value.strip())


def _flatten_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return " ".join(_flatten_text(item) for item in value)
    return ""


def get_course(platform, slug, catalog=CATALOG):
    return next((course for course in catalog.get(platform, ()) if course["slug"] == slug), None)


def get_lesson(course, lesson_id):
    return next((lesson for lesson in course.get("lessons", ()) if lesson["id"] == lesson_id), None)


def get_lesson_neighbors(course, lesson_id):
    lessons = course.get("lessons", ())
    for index, lesson in enumerate(lessons):
        if lesson["id"] == lesson_id:
            return (lessons[index - 1] if index else None,
                    lessons[index + 1] if index + 1 < len(lessons) else None)
    return None, None


def validate_catalog(catalog=CATALOG):
    """Raise ValueError for malformed courses, lessons, steps, or edition links."""
    for platform, courses in catalog.items():
        if platform not in PATHWAYS:
            raise ValueError(f"Unsupported platform: {platform}")
        seen_courses = set()
        for course in courses:
            missing = COURSE_REQUIRED - course.keys()
            if missing or any(course.get(key) in (None, "") for key in COURSE_REQUIRED):
                raise ValueError(f"Missing required course fields: {sorted(missing)}")
            if course["platform"] != platform:
                raise ValueError("Unsupported or mismatched course platform")
            if not _has_text(course["slug"]) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", course["slug"]):
                raise ValueError("Course needs a stable slug")
            if course["slug"] in seen_courses:
                raise ValueError("Duplicate course slug")
            seen_courses.add(course["slug"])
            if not isinstance(course["duration_minutes"], (int, float)) or course["duration_minutes"] < 0:
                raise ValueError("Invalid course duration")
            if course["status"] not in STATUSES or course["difficulty"] not in DIFFICULTIES:
                raise ValueError("Invalid course status or difficulty")
            if course["level"] not in LEVELS:
                raise ValueError("Invalid course level")
            if not isinstance(course["lessons"], (list, tuple)):
                raise ValueError("Lessons must be an ordered collection")
            if course["status"] == "Live" and not course["lessons"]:
                raise ValueError("Published courses need lessons")

            lesson_ids = []
            for lesson in course["lessons"]:
                if not isinstance(lesson, dict) or LESSON_REQUIRED - lesson.keys():
                    raise ValueError("Missing required lesson fields")
                if not _has_text(lesson["id"]) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", lesson["id"]):
                    raise ValueError("Lesson needs a stable ID")
                if lesson["id"] in lesson_ids:
                    raise ValueError("Duplicate lesson ID")
                lesson_ids.append(lesson["id"])
                if not _has_text(lesson["title"]) or not _has_text(lesson["outcome"]):
                    raise ValueError("Lessons need titles and outcomes")
                for field in ("summary", "ftc_relevance", "practice"):
                    if not _has_text(lesson[field]):
                        raise ValueError(f"Lessons need {field.replace('_', ' ')}")
                for field in ("concepts", "required_setup", "checkpoints", "common_mistakes", "completion_checklist", "self_check"):
                    if not isinstance(lesson[field], (list, tuple)) or not lesson[field]:
                        raise ValueError(f"Lessons need {field.replace('_', ' ')}")
                if course["status"] == "Live" and (not isinstance(lesson["estimated_minutes"], (int, float)) or lesson["estimated_minutes"] <= 0):
                    raise ValueError("Published lessons need positive durations")
                if course["status"] == "Live" and not lesson["steps"]:
                    raise ValueError("Published lessons need build steps")
                for step in lesson["steps"]:
                    if not isinstance(step, dict) or STEP_REQUIRED - step.keys() or any(not _has_text(step.get(field)) for field in STEP_REQUIRED):
                        raise ValueError("Build steps need titles, actions, reasons, and results")
                if not lesson["checkpoints"]:
                    raise ValueError("Lessons need checkpoints")
                for item in lesson["self_check"]:
                    if (not isinstance(item, dict) or SELF_CHECK_REQUIRED - item.keys()
                            or any(not _has_text(item.get(field)) for field in SELF_CHECK_REQUIRED)):
                        raise ValueError("Self-checks need questions and answers")
                # Aligned cross-platform titles may name both concepts (for example,
                # "Variables or user parameters"); inspect instructional body copy,
                # where a foreign command would actually misdirect a learner.
                text = _flatten_text({key: value for key, value in lesson.items()
                                      if key not in {"title", "summary"}}).casefold()
                if any(term in text for term in FOREIGN_TERMS[platform]):
                    raise ValueError(f"Unsupported platform terminology in {platform} lesson")

    for platform, courses in catalog.items():
        other = PATHWAYS[platform]["other"]
        for course in courses:
            equivalent = get_course(other, course["equivalent_slug"], catalog=catalog)
            if equivalent is None or equivalent.get("equivalent_slug") != course["slug"]:
                raise ValueError("Broken equivalent-course relationship")
            if course["status"] == "Live":
                if equivalent["status"] != "Live":
                    raise ValueError("Equivalent published course is not live")
                own_ids = tuple(lesson["id"] for lesson in course["lessons"])
                other_ids = tuple(lesson["id"] for lesson in equivalent["lessons"])
                if own_ids != other_ids:
                    raise ValueError("Broken equivalent-lesson ordering")
    return True


validate_catalog()
