"""Catalog-scoped learner progress and presentation data."""

from academy.catalog import CATALOG, PATHWAYS, get_course, get_lesson


def live_courses(platform):
    return tuple(course for course in CATALOG[platform] if course["status"] == "Live")


def valid_lesson(platform, course_slug, lesson_id):
    if platform not in PATHWAYS:
        return None
    course = get_course(platform, course_slug)
    if course is None or course["status"] != "Live":
        return None
    lesson = get_lesson(course, lesson_id)
    return (course, lesson) if lesson else None


def completed_lessons(conn, user_id):
    """Return only rows still present in the current live curriculum."""
    rows = conn.execute(
        "SELECT platform,course_slug,lesson_id,completed_at FROM academy_lesson_progress "
        "WHERE user_id=? ORDER BY completed_at DESC", (user_id,)
    ).fetchall()
    return {(row["platform"], row["course_slug"], row["lesson_id"]): row["completed_at"]
            for row in rows if valid_lesson(row["platform"], row["course_slug"], row["lesson_id"])}


def course_progress(platform, course, completed):
    lessons = course["lessons"]
    done = sum((platform, course["slug"], lesson["id"]) in completed for lesson in lessons)
    total = len(lessons)
    first = next((lesson for lesson in lessons
                  if (platform, course["slug"], lesson["id"]) not in completed), None)
    return {
        "course": course, "completed": done, "total": total,
        "percentage": round(100 * done / total) if total else 0,
        "first_incomplete": first, "complete": bool(total) and done == total,
        "action": "Review course" if total and done == total else
                  "Continue course" if done else "Start course",
    }


def pathway_progress(platform, completed):
    courses = [course_progress(platform, course, completed) for course in live_courses(platform)]
    done = sum(item["completed"] for item in courses)
    total = sum(item["total"] for item in courses)
    resume = next((item for item in courses if item["first_incomplete"]), None)
    return {"platform": platform, "courses": courses, "completed": done, "total": total,
            "percentage": round(100 * done / total) if total else 0,
            "resume": resume, "complete": bool(total) and done == total}


def dashboard_data(completed):
    pathways = {platform: pathway_progress(platform, completed) for platform in PATHWAYS}
    done = sum(item["completed"] for item in pathways.values())
    total = sum(item["total"] for item in pathways.values())
    recent = []
    for (platform, slug, lesson_id), completed_at in sorted(
            completed.items(), key=lambda item: item[1], reverse=True)[:8]:
        course = get_course(platform, slug)
        recent.append({"platform": platform, "course": course,
                       "lesson": get_lesson(course, lesson_id), "completed_at": completed_at})
    return {"pathways": pathways, "completed": done, "total": total,
            "percentage": round(100 * done / total) if total else 0, "recent": recent}
