"""Small EmailJS REST API wrapper for transactional Botfolio emails."""

import json
import logging
import os
import urllib.error
import urllib.request


EMAILJS_ENDPOINT = "https://api.emailjs.com/api/v1.0/email/send"

SERVICE_ID = os.environ.get(
    "EMAILJS_SERVICE_ID",
    "service_40x359u",
).strip()

TEMPLATE_ID = os.environ.get(
    "EMAILJS_TEMPLATE_ID",
    "template_245tr4r",
).strip()

PUBLIC_KEY = os.environ.get(
    "EMAILJS_PUBLIC_KEY",
    "",
).strip()

PRIVATE_KEY = os.environ.get(
    "EMAILJS_PRIVATE_KEY",
    "",
).strip()

FROM_EMAIL = os.environ.get(
    "BOTFOLIO_FROM_EMAIL",
    "noreply@botfoliohq.com",
).strip()

FROM_NAME = os.environ.get(
    "BOTFOLIO_FROM_NAME",
    "Botfolio",
).strip()


def _runtime_setting(name, fallback):
    """Read deployment settings when an email is sent.

    Railway can restart workers independently while a configuration deployment
    is rolling out. Reading the values here avoids retaining an empty or stale
    credential that was captured when this module was first imported.
    """
    return os.environ.get(name, fallback).strip()


def _runtime_config():
    return {
        "service_id": _runtime_setting("EMAILJS_SERVICE_ID", SERVICE_ID),
        "template_id": _runtime_setting("EMAILJS_TEMPLATE_ID", TEMPLATE_ID),
        "public_key": _runtime_setting("EMAILJS_PUBLIC_KEY", PUBLIC_KEY),
        "private_key": _runtime_setting("EMAILJS_PRIVATE_KEY", PRIVATE_KEY),
        "from_email": _runtime_setting("BOTFOLIO_FROM_EMAIL", FROM_EMAIL),
        "from_name": _runtime_setting("BOTFOLIO_FROM_NAME", FROM_NAME),
    }


def is_configured():
    """Return True when the required EmailJS settings are available."""
    config = _runtime_config()
    return bool(
        config["service_id"]
        and config["template_id"]
        and config["public_key"]
    )


def send_email(
    *,
    to_email,
    to_name,
    subject,
    heading,
    message,
    action_url="",
    action_text="",
    event_type="notification",
    team_number="",
    team_name="",
    reply_to="",
    footer="",
    website_url="https://botfoliohq.com",
    greeting="",
    intro="",
    purpose="",
    security_notice="",
    signoff="Botfolio",
):
    """Send one EmailJS template with dynamic transactional content.

    Returns True when EmailJS accepts the request.

    Email failures are treated as non-fatal so an email problem does not undo
    account creation, password-reset token creation, or team membership changes.
    """
    config = _runtime_config()
    if not (
        config["service_id"]
        and config["template_id"]
        and config["public_key"]
    ):
        logging.warning(
            "EmailJS is not configured. "
            "Service loaded: %s, template loaded: %s, public key loaded: %s",
            bool(config["service_id"]),
            bool(config["template_id"]),
            bool(config["public_key"]),
        )
        return False

    template_params = {
        # Include both names in case the EmailJS template uses {{email}}
        # instead of {{to_email}}.
        "email": to_email,
        "to_email": to_email,
        "to_name": to_name,
        "from_name": config["from_name"],
        "from_email": config["from_email"],
        "reply_to": reply_to or config["from_email"],
        "subject": subject,
        "heading": heading,
        "message": message,
        "action_url": action_url,
        "action_text": action_text,
        "event_type": event_type,
        "team_number": str(team_number) if team_number else "",
        "team_name": team_name,
        "footer": footer,
        "website_url": website_url,
        "greeting": greeting,
        "intro": intro,
        "purpose": purpose,
        "security_notice": security_notice,
        "signoff": signoff,
    }

    payload = {
        "service_id": config["service_id"],
        "template_id": config["template_id"],
        "user_id": config["public_key"],
        "template_params": template_params,
    }

    if config["private_key"]:
        payload["accessToken"] = config["private_key"]

    encoded_payload = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        EMAILJS_ENDPOINT,
        data=encoded_payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode(
                "utf-8",
                errors="replace",
            )

            logging.info(
                "EmailJS accepted email for %s. Status: %s. Response: %s",
                to_email,
                response.status,
                response_body,
            )

            return 200 <= response.status < 300

    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        logging.error(
            "EmailJS rejected email for %s. "
            "Status: %s. Reason: %s. Private key loaded: %s. Response: %s",
            to_email,
            error.code,
            error.reason,
            bool(config["private_key"]),
            error_body,
        )

        return False

    except urllib.error.URLError as error:
        logging.error(
            "EmailJS connection failed for %s. Reason: %s",
            to_email,
            error.reason,
        )
        return False

    except TimeoutError:
        logging.exception(
            "EmailJS request timed out for %s",
            to_email,
        )
        return False

    except OSError:
        logging.exception(
            "EmailJS operating-system or network error for %s",
            to_email,
        )
        return False

    except Exception:
        logging.exception(
            "Unexpected EmailJS error for %s",
            to_email,
        )
        return False
