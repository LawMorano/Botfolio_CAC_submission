"""OpenAI-backed safety checks and structured FTC design reviews."""

import base64
import os
import re

from pydantic import BaseModel, Field


MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


SCORING_RUBRIC = """Score each category on a true 0-100 scale using these anchors:
- 90-100: exceptional; the supplied evidence shows a competition-ready,
  extensively validated design with only minor concerns.
- 70-89: strong; the design is credible and well supported, with manageable
  weaknesses or limited validation still needed.
- 50-69: plausible but uncertain; the concept has merit, but important risks,
  implementation details, or validation evidence are missing.
- 30-49: weak; the supplied evidence shows major unresolved problems likely to
  impair construction, maintenance, or reliable operation.
- 0-29: critical; the supplied evidence shows the design is probably
  nonfunctional or fundamentally unsuitable without major redesign.

Score reliability, buildability, and serviceability independently. Set the
overall score to their arithmetic mean, rounded to the nearest whole number.
Missing information is uncertainty, not proof of a defect: list it under
missing_information and lower confidence, but do not assign an extremely low
score unless the supplied evidence demonstrates a critical problem. Make every
score consistent with the wording of the answer and summary; for example,
"moderate risk" normally belongs in the 50-69 range, not the 0-29 range."""


class ModerationRejected(ValueError):
    pass


class ModerationUnavailable(ValueError):
    pass


# The Moderation API catches contextual harm, hate, sexual content, and
# violence. This small local guard fills a different gap: ordinary profanity
# that is inappropriate for a student community but may not be harmful enough
# for a general-purpose safety classifier to flag.
_INAPPROPRIATE_WORDS = {
    "asshole", "bastard", "bitch", "bullshit", "cunt", "dick", "douche",
    "faggot", "fuck", "fucker", "fucking", "motherfucker", "nigger", "porn",
    "pussy", "shit", "slut", "whore",
}
_LEET_TRANSLATION = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})


def contains_inappropriate_language(text):
    normalized = (text or "").lower().translate(_LEET_TRANSLATION)
    words = re.findall(r"[a-z]+", normalized)
    return any(word in _INAPPROPRIATE_WORDS for word in words)


def moderate_public_content(*, texts=(), image_bytes=(), use_api=True):
    """Apply local screening; hosted moderation is optional in the CAC demo."""
    parts = [str(value).strip() for value in texts if value is not None and str(value).strip()]
    text = "\n".join(parts)[:12000]
    if contains_inappropriate_language(text):
        raise ModerationRejected(
            "That content contains language that is not allowed on Botfolio."
        )

    if os.environ.get("CAC_ISOLATED_DEPLOYMENT") == "true":
        # CAC has no main-site API key. Keep its local language guard while
        # allowing demo registration and uploads without an external account.
        use_api = False

    images = list(image_bytes)
    if not use_api or (not text and not images):
        return
    if not is_configured():
        raise ModerationUnavailable(
            "The safety check is temporarily unavailable. Nothing was published; please try again."
        )

    inputs = []
    if text:
        inputs.append({"type": "text", "text": text})
    for raw in images:
        encoded = base64.b64encode(raw).decode("ascii")
        inputs.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
        })
    try:
        moderation = _client().moderations.create(
            model="omni-moderation-latest", input=inputs
        )
    except Exception as exc:
        raise ModerationUnavailable(
            "The safety check is temporarily unavailable. Nothing was published; please try again."
        ) from exc
    if any(result.flagged for result in moderation.results):
        raise ModerationRejected(
            "That content cannot be published because it did not pass Botfolio's safety check."
        )


class DesignReview(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    reliability_score: int = Field(ge=0, le=100)
    buildability_score: int = Field(ge=0, le=100)
    serviceability_score: int = Field(ge=0, le=100)
    answer: str
    summary: str
    strengths: list[str]
    concerns: list[str]
    suggestions: list[str]
    missing_information: list[str]


def is_configured():
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _client():
    if not is_configured():
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def review_design(*, title, description, category, season, team_number, focus,
                  question, image_data_url=None, safety_identifier=None):
    """Moderate the request, then return a schema-validated robotics review."""
    client = _client()
    moderation_text = "\n".join(filter(None, [title, description, question]))[:12000]
    moderation_inputs = [{"type": "text", "text": moderation_text}]
    if image_data_url:
        moderation_inputs.append({"type": "image_url", "image_url": {"url": image_data_url}})
    moderation = client.moderations.create(
        model="omni-moderation-latest", input=moderation_inputs
    )
    if any(result.flagged for result in moderation.results):
        raise ModerationRejected(
            "This review request could not be processed by the safety filter."
        )

    prompt = f"""Review this FTC robotics design using only the supplied evidence.
Do not invent dimensions, materials, mechanisms, tests, or performance. Identify
missing information explicitly. Give constructive, age-appropriate, practical
engineering feedback for realistic FTC resources. Do not certify safety or claim
the robot will definitely succeed or fail.

{SCORING_RUBRIC}

Title: {title}
Description: {description or 'No description provided'}
Category: {category or 'Not provided'}
FTC season: {season or 'Not provided'}
FTC team: {team_number or 'Not provided'}
Focus: {focus or 'General review'}
Student question: {question or 'Provide a general review.'}
"""
    content = [{"type": "input_text", "text": prompt}]
    if image_data_url:
        content.append({"type": "input_image", "image_url": image_data_url})
    kwargs = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": "You are Botfolio's narrowly scoped FTC mechanical design reviewer."},
            {"role": "user", "content": content},
        ],
        "text_format": DesignReview,
    }
    if safety_identifier:
        kwargs["safety_identifier"] = safety_identifier
    response = client.responses.parse(**kwargs)
    if response.output_parsed is None:
        raise RuntimeError("OpenAI returned no structured review.")
    return response.output_parsed.model_dump()
