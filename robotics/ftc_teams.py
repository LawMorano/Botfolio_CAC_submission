"""Look up real FTC teams from FTC Scout's public REST API.

Botfolio only stores teams that someone has claimed. To let anyone search for
*any* real FTC team — the way FTC Scout's own search works — we query FTC Scout's
public API on demand: a real team resolves to its official name and location even
without a Botfolio account, and a number that is not a real team resolves to
nothing.

Every call fails soft. If the registry cannot be reached the site keeps working;
it just cannot confirm off-site teams that moment (raised as FtcApiError so the
caller can say so, rather than pretending the team does not exist).
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.ftcscout.org/rest/v1"
_TIMEOUT = 6                       # seconds; the UI must not hang on a slow API
_CACHE_TTL = 60 * 60 * 12          # 12h — official team names change rarely
_CACHE_MAX = 2000
_USER_AGENT = "Botfolio (+https://botfoliohq.com)"

_cache = {}                        # key -> (expires_at_monotonic, value)


class FtcApiError(RuntimeError):
    """The FTC team registry could not be reached or returned an error."""


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    if hit:
        _cache.pop(key, None)
    return None


def _cache_put(key, value):
    if len(_cache) >= _CACHE_MAX:    # crude bound; team data is not precious
        _cache.clear()
    _cache[key] = (time.monotonic() + _CACHE_TTL, value)


def _fetch(path, timeout=None):
    """GET API_BASE+path and return parsed JSON. Isolated so tests can stub it."""
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize(raw):
    if not isinstance(raw, dict) or not raw.get("number"):
        return None
    location = ", ".join(
        part for part in (raw.get("city"), raw.get("state"), raw.get("country")) if part
    )
    return {
        "number": int(raw["number"]),
        "name": (raw.get("name") or "").strip() or f"Team {raw['number']}",
        "location": location,
        "rookie_year": raw.get("rookieYear"),
        "website": (raw.get("website") or "").strip() or None,
    }


def lookup(number, timeout=None):
    """Return a normalized team dict, or None if no such FTC team exists.

    Raises FtcApiError if the registry cannot be reached — which is distinct from
    a confirmed 'no such team' (None), so callers do not report an outage as a
    non-existent team. `timeout` bounds a single request (e.g. for typeahead).
    """
    key = f"team:{int(number)}"
    cached = _cache_get(key)
    if cached is not None:
        return cached or None          # "" sentinel = confirmed-absent
    try:
        data = _fetch(f"/teams/{int(number)}", timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _cache_put(key, "")
            return None
        raise FtcApiError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise FtcApiError(str(exc)) from exc
    team = _normalize(data)
    _cache_put(key, team or "")
    return team


def search(text, limit=25, timeout=None):
    """Return real FTC teams matching text (possibly empty).

    Raises FtcApiError if the registry cannot be reached. `timeout` bounds the
    single request, so the interactive search box can fail fast.
    """
    text = (text or "").strip()
    if not text:
        return []
    limit = max(1, min(int(limit), 50))
    key = f"search:{limit}:{text.lower()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    query = urllib.parse.quote(text)
    try:
        data = _fetch(f"/teams/search?searchText={query}&limit={limit}", timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _cache_put(key, [])
            return []
        raise FtcApiError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise FtcApiError(str(exc)) from exc
    teams = [t for t in (_normalize(item) for item in (data or [])) if t][:limit]
    _cache_put(key, teams)
    return teams


def describe(number):
    """Classify an unclaimed team number for the team page.

    Returns {"state": "found"|"absent"|"error", "team": dict|None}.
    """
    try:
        team = lookup(number)
    except FtcApiError:
        return {"state": "error", "team": None}
    return {"state": "found" if team else "absent", "team": team}
