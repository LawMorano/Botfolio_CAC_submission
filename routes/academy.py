"""Public CAD lessons with private learner progress."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import app as core
import db
from academy.progress import completed_lessons, course_progress, dashboard_data, pathway_progress, valid_lesson

from academy.catalog import (
    CATALOG, LEVELS, PATHWAYS, get_course, get_lesson, get_lesson_neighbors,
)


academy_bp = Blueprint("academy", __name__)


@academy_bp.get("/learn")
def learn():
    return render_template("academy/index.html", pathways=PATHWAYS, levels=LEVELS)


@academy_bp.get("/learn/<platform>")
def learn_pathway(platform):
    pathway = PATHWAYS.get(platform)
    if pathway is None:
        abort(404)
    user = core.current_user()
    completed = completed_lessons(db.get_db(), user["id"]) if user else None
    progress = pathway_progress(platform, completed) if completed is not None else None
    return render_template("academy/pathway.html", platform=platform, progress=progress,
                           pathway=pathway, courses=CATALOG[platform],
                           other=PATHWAYS[pathway["other"]])


@academy_bp.get("/learn/<platform>/<course_slug>")
def learn_course(platform, course_slug):
    if platform not in PATHWAYS:
        abort(404)
    course = get_course(platform, course_slug)
    if course is None or course["status"] != "Live":
        abort(404)
    other_slug = PATHWAYS[platform]["other"]
    other_course = get_course(other_slug, course["equivalent_slug"])
    user = core.current_user()
    completed = completed_lessons(db.get_db(), user["id"]) if user else None
    progress = course_progress(platform, course, completed) if completed is not None else None
    return render_template("academy/course.html", platform=platform, progress=progress,
                           completed_lessons=completed,
                           pathway=PATHWAYS[platform], course=course,
                           other_platform=other_slug,
                           other=PATHWAYS[other_slug], other_course=other_course,
                           related=[get_course(platform, slug) for slug in course["related"]])


@academy_bp.get("/learn/<platform>/<course_slug>/lessons/<lesson_id>")
def learn_lesson(platform, course_slug, lesson_id):
    if platform not in PATHWAYS:
        abort(404)
    course = get_course(platform, course_slug)
    if course is None or course["status"] != "Live":
        abort(404)
    lesson = get_lesson(course, lesson_id)
    if lesson is None:
        abort(404)
    previous_lesson, next_lesson = get_lesson_neighbors(course, lesson_id)
    other_platform = PATHWAYS[platform]["other"]
    other_course = get_course(other_platform, course["equivalent_slug"])
    other_lesson = get_lesson(other_course, lesson_id) if other_course and other_course["status"] == "Live" else None
    lesson_number = next(index for index, item in enumerate(course["lessons"], 1)
                         if item["id"] == lesson_id)
    user = core.current_user()
    completed = completed_lessons(db.get_db(), user["id"]) if user else None
    is_complete = (platform, course_slug, lesson_id) in completed if completed is not None else False
    return render_template(
        "academy/lesson.html", platform=platform, pathway=PATHWAYS[platform],
        is_complete=is_complete,
        course=course, lesson=lesson, lesson_number=lesson_number,
        previous_lesson=previous_lesson, next_lesson=next_lesson,
        other_platform=other_platform, other=PATHWAYS[other_platform],
        other_course=other_course, other_lesson=other_lesson,
    )


@academy_bp.post("/learn/<platform>/<course_slug>/lessons/<lesson_id>/completion")
@core.login_required
def learn_completion(platform, course_slug, lesson_id):
    if valid_lesson(platform, course_slug, lesson_id) is None:
        abort(404)
    action = request.form.get("action")
    if action not in {"complete", "incomplete"}:
        abort(400)
    conn = db.get_db()
    key = (core.current_user()["id"], platform, course_slug, lesson_id)
    if action == "complete":
        conn.execute(
            "INSERT INTO academy_lesson_progress(user_id,platform,course_slug,lesson_id) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id,platform,course_slug,lesson_id) DO NOTHING", key)
        flash("Lesson marked complete.", "success")
    else:
        conn.execute("DELETE FROM academy_lesson_progress WHERE user_id=? AND platform=? "
                     "AND course_slug=? AND lesson_id=?", key)
        flash("Lesson marked incomplete.", "success")
    conn.commit()
    return redirect(url_for("learn_lesson", platform=platform,
                            course_slug=course_slug, lesson_id=lesson_id))


@academy_bp.get("/learn/my-progress")
@core.login_required
def learn_my_progress():
    completed = completed_lessons(db.get_db(), core.current_user()["id"])
    return render_template("academy/progress.html", data=dashboard_data(completed),
                           pathways=PATHWAYS)
