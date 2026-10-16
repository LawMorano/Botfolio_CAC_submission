"""Small adapter for the official FIRST FRC Events team registry.

The Events API is season based, even when all Botfolio needs is a team profile.
We try the configured season first and the previous season second so an
off-season visit can still find a team that has not registered for the new year.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date


API_BASE = "https://frc-api.firstinspires.org/v3.0"
_TIMEOUT = 6
_CACHE_TTL = 60 * 60 * 12
_CACHE_MAX = 2000
_USER_AGENT = "Botfolio (+https://botfoliohq.com)"

_cache = {}


class FrcApiError(RuntimeError):
    """The FRC registry is unavailable or has not been configured."""


def _credentials():
    username = (os.environ.get("FRC_API_USERNAME") or "").strip()
    token = (os.environ.get("FRC_API_TOKEN") or "").strip()
    if not username or not token:
        raise FrcApiError("FRC registry credentials are not configured")
    return username, token


def _season():
    raw = (os.environ.get("FRC_API_SEASON") or "").strip()
    try:
        return int(raw) if raw else date.today().year
    except ValueError:
        return date.today().year


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    if hit:
        _cache.pop(key, None)
    return None


def _cache_put(key, value):
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.monotonic() + _CACHE_TTL, value)


def _fetch(path, timeout=None):
    """Fetch one API response. Kept separate so the registry is easy to test."""
    username, token = _credentials()
    encoded = base64.b64encode(f"{username}:{token}".encode()).decode("ascii")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Basic {encoded}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout or _TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize(raw):
    if not isinstance(raw, dict) or not raw.get("teamNumber"):
        return None
    number = int(raw["teamNumber"])
    location = ", ".join(
        part for part in (
            raw.get("city"), raw.get("stateProv"), raw.get("country"),
        ) if part
    )
    website = (raw.get("website") or "").strip()
    parsed_website = urllib.parse.urlparse(website)
    if parsed_website.scheme not in {"http", "https"} or not parsed_website.netloc:
        website = None
    return {
        "number": number,
        "name": (raw.get("nameFull") or raw.get("nameShort") or "").strip()
                or f"Team {number}",
        "location": location,
        "rookie_year": raw.get("rookieYear"),
        "website": website,
    }


def lookup(number, timeout=None):
    """Return an official FRC team, or ``None`` when it is not registered."""
    number = int(number)
    key = f"team:{number}:{_season()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached or None

    for season in (_season(), _season() - 1):
        query = urllib.parse.urlencode({"teamNumber": number})
        try:
            payload = _fetch(f"/{season}/teams?{query}", timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 404}:
                continue
            raise FrcApiError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise FrcApiError(str(exc)) from exc
        teams = payload.get("teams", []) if isinstance(payload, dict) else []
        team = _normalize(teams[0]) if teams else None
        if team:
            _cache_put(key, team)
            return team

    _cache_put(key, "")
    return None


def search(text, limit=25, timeout=None):
    """The official API has no name query, so remote search is number-only."""
    text = (text or "").strip()
    if not text.isdigit():
        return []
    team = lookup(int(text), timeout=timeout)
    return [team] if team else []


def describe(number):
    try:
        team = lookup(number)
    except FrcApiError:
        return {"state": "error", "team": None}
    return {"state": "found" if team else "absent", "team": team}
