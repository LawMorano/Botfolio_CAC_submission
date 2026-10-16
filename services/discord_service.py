"""Best-effort Discord notifications for newly published designs."""

import json
import logging
import threading
import urllib.error
import urllib.request


logger = logging.getLogger(__name__)


def _post_webhook(webhook_url, payload):
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Botfolio-Showcase/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        return True
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # Never log the request or URL: Discord webhook URLs contain a secret.
        logger.warning("Discord showcase notification failed: %s", exc.__class__.__name__)
        return False


def notify_design_published(
    webhook_url, *, design_url, title, author, description="", image_url=""
):
    """Queue a Discord embed without delaying or failing the publish request."""
    if not webhook_url:
        return False

    summary = " ".join((description or "").split())
    if len(summary) > 300:
        summary = summary[:297].rstrip() + "..."

    embed = {
        "title": str(title)[:256],
        "url": design_url,
        "description": summary or "A new design was published on Botfolio.",
        "color": 0x2F80ED,
        "author": {"name": f"Published by {str(author)[:240]}"},
        "footer": {"text": "Botfolio Showcase"},
    }
    if image_url:
        embed["image"] = {"url": image_url}
    payload = {
        "username": "Botfolio Showcase",
        "content": "New design published on Botfolio",
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }
    threading.Thread(
        target=_post_webhook,
        args=(webhook_url, payload),
        daemon=True,
        name="discord-showcase-notification",
    ).start()
    return True
