"""The OpenID Connect half of "Sign in with Google", using only the stdlib.

A server-side OAuth 2.0 authorization-code flow with PKCE. Nothing here knows
about Flask, Botfolio's tables, or sessions -- it takes a code and hands back a
verified identity, so the routes above it can stay about accounts.

No new dependency is needed because of one specific property of this flow: the
id_token is fetched by us, over a TLS channel we validated, from an endpoint we
authenticated to with the client secret. OpenID Connect Core 1.0 section
3.1.3.7 clause 6 says a token received that way may be trusted on the strength
of that TLS server validation instead of its signature, and Google documents
the same exemption. That is what removes the RS256/JWKS requirement rather than
working around it -- there is no RSA verification in the standard library, and
hand-rolling PKCS#1 v1.5 is exactly the code nobody should hand-roll.

The exemption is narrow, so the boundary is enforced structurally:
_claims_from_id_token is private and is called from exactly one place, the
token-exchange path in identity_from_code. An id_token arriving from anywhere
else -- a browser POST, a One Tap credential, a query parameter -- is an
unauthenticated string and would have to be fully signature-verified. Do not
give that function a second caller.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from infra.settings import settings

logger = logging.getLogger(__name__)

# Hardcoded rather than read from the discovery document: Google's endpoints are
# stable, and fetching discovery on every sign-in buys a round trip and a new
# failure mode for nothing. Re-check them at review time, not at runtime.
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPE = "openid email profile"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

HTTP_TIMEOUT = 10
# Bounded read: a response body here is a few hundred bytes, and an unbounded
# read() against a remote host is an out-of-memory lever held by someone else.
MAX_BODY = 64 * 1024
# Tolerance for ordinary clock drift between us and Google, in seconds.
CLOCK_LEEWAY = 60

GENERIC_FAILURE = "Sign-in could not be completed. Please try again."


class GoogleAuthError(Exception):
    """A sign-in that cannot be completed, carrying text safe to show a user.

    Nothing that reaches str(exc) may contain a token, an authorization code, or
    Google's error_description -- these messages are flashed onto a page.
    """


def pkce_challenge(verifier):
    """BASE64URL(SHA256(verifier)) with the padding stripped, per RFC 7636."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_flow_secrets():
    """The three one-time values an authorization request has to remember."""
    return {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        # 86 characters of [A-Za-z0-9_-]; RFC 7636 allows 43 to 128.
        "verifier": secrets.token_urlsafe(64),
    }


def authorization_url(state, nonce, verifier):
    """Where to send the browser to start the flow."""
    params = {
        "client_id": settings.google_client_id,
        # Byte-identical to the value repeated in the token exchange, and to a
        # URI registered in the Google console, or the exchange is rejected.
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        # No refresh token: that is a long-lived credential we would then have
        # to store and protect, for a feature that needs one sign-in moment.
        "access_type": "online",
        # Without this, a browser with one live Google session is signed in
        # silently, so "use a different account" becomes impossible.
        "prompt": "select_account",
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"{AUTH_ENDPOINT}?{query}"


def _send(request):
    """Perform one outbound call, or raise a GoogleAuthError with safe copy."""
    # Certificate chain and hostname verification, never disabled -- not even
    # locally, where a broken local trust store is a reason to fix the store.
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(
            request, timeout=HTTP_TIMEOUT, context=context
        ) as response:
            return json.loads(response.read(MAX_BODY).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = {}
        try:
            parsed = json.loads(exc.read(MAX_BODY) or b"{}")
            # A JSON body is not necessarily a JSON object, and an error path
            # that raises its own AttributeError reports nothing at all.
            if isinstance(parsed, dict):
                detail = parsed
        except (ValueError, OSError):
            pass
        # The error code only. error_description can echo values we submitted.
        logger.warning(
            "Google rejected a request: HTTP %s (%s)",
            exc.code, detail.get("error", "unknown"),
        )
        raise GoogleAuthError(GENERIC_FAILURE) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # A Google outage has to degrade to "try again later", never to a 500
        # and never to a half-created account.
        logger.warning("Google request failed: %s", exc.__class__.__name__)
        raise GoogleAuthError(
            "Google sign-in is temporarily unavailable. "
            "You can sign in with your password."
        ) from None


def _post_form(url, fields):
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("ascii"),
        headers={
            # Google will not accept a JSON body at the token endpoint.
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _send(request)


def _get_json(url, access_token):
    request = urllib.request.Request(
        url,
        # Never as ?access_token=: that form is deprecated and leaks the
        # credential into every log and proxy along the way.
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    return _send(request)


def _claims_from_id_token(id_token, expected_nonce):
    """Decode and validate an id_token that we just fetched ourselves.

    PRIVATE, and deliberately so -- see the module docstring. The trust here
    rests on the channel the token arrived on, so a token from any other
    channel must not be handed to this function.
    """
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        raise GoogleAuthError(GENERIC_FAILURE)
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, TypeError):
        raise GoogleAuthError(GENERIC_FAILURE) from None
    if not isinstance(claims, dict):
        raise GoogleAuthError(GENERIC_FAILURE)

    now = int(time.time())
    problem = None
    if claims.get("iss") not in ISSUERS:
        problem = "iss"
    else:
        audience = claims.get("aud")
        if isinstance(audience, str):
            audiences = [audience]
        elif isinstance(audience, list):
            audiences = audience
        else:
            # A number, an object, a missing claim -- anything outside the two
            # shapes the spec allows is refused rather than coerced. list(5)
            # raises TypeError, and that would be a 500 reachable from a
            # response body, on a path whose whole job is to distrust it.
            audiences = []
        if not any(isinstance(value, str)
                   and hmac.compare_digest(value, settings.google_client_id)
                   for value in audiences):
            problem = "aud"
        elif len(audiences) > 1 and not hmac.compare_digest(
                str(claims.get("azp", "")), settings.google_client_id):
            # OIDC Core 1.0 3.1.3.7 clauses 3-4: a token addressed to several
            # audiences has to name us as the authorized party. Without this,
            # a token minted for some other client that merely lists us as an
            # audience would be accepted as one of ours.
            problem = "azp"
    if problem is None:
        try:
            if int(claims.get("exp", 0)) < now - CLOCK_LEEWAY:
                problem = "exp"
            elif int(claims.get("iat", 0)) > now + CLOCK_LEEWAY:
                problem = "iat"
        except (TypeError, ValueError):
            problem = "exp"
    if problem is None and (
        # An empty expectation must fail, not match: compare_digest("", "") is
        # true, so a caller that lost its nonce would accept a token carrying
        # none -- the check disabling itself in exactly the case it exists for.
        not expected_nonce
        or not hmac.compare_digest(str(claims.get("nonce", "")), expected_nonce)
    ):
        # The nonce binds this token to this browser's own request, so a
        # captured token cannot be replayed into somebody else's flow.
        problem = "nonce"
    if problem:
        logger.warning("Google id_token rejected: bad %s", problem)
        raise GoogleAuthError(GENERIC_FAILURE)
    return claims


def _verified_email(claims):
    """The address, but only if Google says it has proven it.

    email_verified is a JSON boolean, though some Google surfaces have
    historically sent the string. Accept exactly those two and reject the rest:
    an unverified Google address must never be able to match a Botfolio
    account, or the email-matching rule becomes an account-takeover primitive.
    """
    email = (claims.get("email") or "").strip().lower()
    if not email:
        return ""
    verified = claims.get("email_verified")
    if verified is True or (isinstance(verified, str) and verified.lower() == "true"):
        return email
    raise GoogleAuthError("Your Google account's email address is not verified.")


def identity_from_code(code, verifier, nonce):
    """Trade an authorization code for a verified {sub, email, name}."""
    payload = _post_form(TOKEN_ENDPOINT, {
        "code": code,
        "client_id": settings.google_client_id,
        # client_secret_post is Google's documented method; do not switch this
        # to an Authorization: Basic header.
        "client_secret": settings.google_client_secret,
        # Identical to the authorization request, or Google answers
        # invalid_grant.
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    if not isinstance(payload, dict):
        raise GoogleAuthError(GENERIC_FAILURE)

    claims = _claims_from_id_token(payload.get("id_token"), nonce)
    subject = (claims.get("sub") or "").strip()
    if not subject:
        raise GoogleAuthError(GENERIC_FAILURE)

    email = _verified_email(claims)
    name = (claims.get("name") or "").strip()
    if not email:
        # Granular consent can leave the email claim out of the id_token. Do
        # not read the returned "scope" string to decide this -- it comes back
        # as full URLs and is easy to misparse. Ask for the data instead.
        access_token = payload.get("access_token")
        if access_token:
            info = _get_json(USERINFO_ENDPOINT, access_token)
            if not isinstance(info, dict):
                raise GoogleAuthError(GENERIC_FAILURE)
            # Two responses, so make sure they describe one person before
            # trusting a field from the second one.
            if hmac.compare_digest(str(info.get("sub", "")), subject):
                email = _verified_email(info)
                name = name or (info.get("name") or "").strip()
    if not email:
        raise GoogleAuthError(
            "Botfolio needs your Google email address to sign you in."
        )
    return {"sub": subject, "email": email, "name": name}


def subject_fingerprint(subject):
    """A short, non-reversible handle for logs and the security-events table.

    The raw sub is a Google account identifier and does not belong in a table
    that may one day be shipped to a log aggregator.
    """
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
