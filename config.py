"""Editable moderation and submission limits for Botfolio."""

ADMIN_EMAIL = "lmorano@botfoliohq.com"
ADMIN_USERNAME = "BotfolioAdmin"
TERMS_VERSION = "2026-08-14"
PRIVACY_VERSION = "2026-08-16"
# Whenever any linked legal document changes, bump this value and replace the
# summaries below. Existing users will then see and acknowledge the explanation
# immediately after their next successful sign-in.
LEGAL_NOTICE_VERSION = "2026-08-16"
LEGAL_CHANGE_SUMMARY = (
    "Privacy Policy: AI questions and responses are private to the requesting account.",
    "Unsaved AI chats are deleted after three days; chats a user saves remain private in that user's profile.",
)
UPLOAD_CERTIFICATION_VERSION = "2026-08-12"
SUPPORT_EMAIL = "support@botfoliohq.com"
PRIVACY_EMAIL = "privacy@botfoliohq.com"
SECURITY_EMAIL = "security@botfoliohq.com"
COPYRIGHT_EMAIL = "copyright@botfoliohq.com"
LEGAL_EMAIL = "legal@botfoliohq.com"

UPLOAD_LIMIT_10_MINUTES = 3
UPLOAD_LIMIT_DAILY = 10
MAX_TAGS_PER_DESIGN = 8
MAX_TAG_LENGTH = 30
NEW_TAG_LIMIT_PER_HOUR = 12
VISIT_COOLDOWN_MINUTES = 30
# Public design counters intentionally start fresh after the crawler-inflated
# request counter was replaced with an engaged-browser counter. Keep the label
# beside every displayed total so nobody mistakes it for an all-time number
# from before the measurement change.
VIEW_COUNT_START_LABEL = "10/12/26"
# One person deciding to grab a file is one download. Browsers resume, retry
# and revalidate large models constantly, and people re-click the link after a
# failed save, so anything shorter counts the same intent several times.
DOWNLOAD_COOLDOWN_MINUTES = 1440
# How many different designs one account can take the CAD for in a day, whether
# that is the stored file or a click through to the CAD host. Deliberately the
# same window as the cooldown above, so a design you already took today never
# costs a second slot however many times you fetch it again.
DAILY_DOWNLOAD_LIMIT = 5
TAG_IMMEDIATE_REMOVAL_SCORE = -6  # "below -5"
TAG_LOW_SCORE = -2
TAG_LOW_SCORE_DAYS = 30
