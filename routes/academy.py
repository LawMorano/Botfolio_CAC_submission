"""Read-only public CAD Academy pages."""

from flask import Blueprint, abort, render_template

from academy.catalog import CATALOG, LEVELS, PATHWAYS, get_course


academy_bp = Blueprint("academy", __name__)


@academy_bp.get("/learn")
def learn():
    return render_template("academy/index.html", pathways=PATHWAYS, levels=LEVELS)


@academy_bp.get("/learn/<platform>")
def learn_pathway(platform):
    pathway = PATHWAYS.get(platform)
    if pathway is None:
        abort(404)
    return render_template("academy/pathway.html", platform=platform,
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
    return render_template("academy/course.html", platform=platform,
                           pathway=PATHWAYS[platform], course=course,
                           other_platform=other_slug,
                           other=PATHWAYS[other_slug], other_course=other_course,
                           related=[get_course(platform, slug) for slug in course["related"]])
