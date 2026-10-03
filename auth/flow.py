"""Sign-up, sign-in, and bot protection for the public deployment.

Why this module exists
----------------------
The Streamlit app sat behind a public Funnel URL with ``disable_signup=False``,
no CAPTCHA, and an admin-only provisioning note in the UI. Anyone who found the
URL could create accounts, and each attempt sent mail through Supabase's shared
(and heavily throttled) sender.

Three things are handled here, each deliberately separated from the Streamlit
layer so they can be tested without a browser:

1. **CAPTCHA configuration** — the site key is public (it ships to the browser);
   the secret never leaves the server. Supabase verifies the token *server
   side*, so a client that skips the widget still gets rejected. The widget is
   usability; the server check is the actual control.

2. **Password policy** — mirrored client side so a user learns the rule before
   a round-trip, then enforced by Supabase regardless.

3. **Error classification** — Supabase's raw messages distinguish "already
   registered" from "bad password", which leaks account existence to anyone
   probing the public URL. Sign-up responses are therefore deliberately
   uniform.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

ENV_CAPTCHA_ENABLED = "AUTH_CAPTCHA_ENABLED"
ENV_CAPTCHA_SITE_KEY = "HCAPTCHA_SITE_KEY"
ENV_CAPTCHA_SECRET = "HCAPTCHA_SECRET"

# hCaptcha's documented test credentials. Supabase verifies against the secret,
# and the pairs match — so the whole sign-up path (widget -> token -> Supabase
# server-side verify -> GoTrue) can be exercised end to end before a real
# hCaptcha account exists. See docs/AUTH-SETUP.md.
HCAPTCHA_TEST_SITE_KEY = "10000000-ffff-ffff-ffff-000000000001"
HCAPTCHA_TEST_SECRET = "0x0000000000000000000000000000000000000000"

MIN_PASSWORD_LENGTH = 8

# Sign-up answers with this string whether or not the address was already
# registered. It is a single constant rather than two similar literals so the
# two paths cannot drift apart and quietly become an account-existence oracle
# on a public URL. Do not inline this at a call site.
SIGNUP_UNIFORM_MESSAGE = (
    "If that address can be registered, a confirmation link is on its way. "
    "Check your inbox and spam folder before signing in."
)

# Supabase's default is 2 confirmation emails per hour, project-wide. That is
# lower than the number of people who will try a hackathon demo, and the third
# person silently receives nothing. Raised in the project config; this constant
# records the value we require so drift is detectable.
RECOMMENDED_EMAIL_RATE_LIMIT = 30


@dataclass(frozen=True)
class CaptchaConfig:
    """Resolved CAPTCHA configuration for one deployment."""

    enabled: bool
    site_key: str
    secret: str
    using_test_keys: bool

    @property
    def has_site_key(self) -> bool:
        return bool(self.site_key.strip())


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def captcha_config() -> CaptchaConfig:
    """Read CAPTCHA config from the environment.

    Defaults to **disabled** when nothing is configured, so a developer cloning
    the repo is not blocked by a service they have no keys for. Production turns
    it on by setting the three variables, which is also what makes the setting
    visible in a deployment review rather than buried in code.
    """
    site_key = (os.environ.get(ENV_CAPTCHA_SITE_KEY) or "").strip()
    secret = (os.environ.get(ENV_CAPTCHA_SECRET) or "").strip()
    using_test = site_key == HCAPTCHA_TEST_SITE_KEY or secret == HCAPTCHA_TEST_SECRET
    enabled = _env_flag(ENV_CAPTCHA_ENABLED, default=False) or bool(site_key and secret)
    return CaptchaConfig(enabled=enabled, site_key=site_key, secret=secret,
                         using_test_keys=using_test)


# --------------------------------------------------------------------------- #
# Password policy
# --------------------------------------------------------------------------- #

def password_problem(password: str) -> str | None:
    """Return a human-readable reason the password is unacceptable, or None.

    Mirrors what Supabase enforces (``password_min_length``). Deliberately
    checked before the network call: a round-trip that comes back "too short"
    is a worse experience than saying so immediately, and it avoids spending a
    slice of the project-wide auth rate limit on a predictable failure.
    """
    if not password:
        return "Enter a password."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.strip() != password:
        return "Password must not start or end with a space."
    if len(set(password)) == 1:
        return "Password must not be a single repeated character."
    return None


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #

# Substrings Supabase/GoTrue uses. Matched case-insensitively.
_ALREADY_REGISTERED = ("already registered", "already been registered",
                       "user already exists")
_RATE_LIMITED = ("rate limit", "too many requests", "over_email_send_rate_limit",
                 "email rate limit exceeded")
_CAPTCHA_FAILED = ("captcha", "hcaptcha", "security check")
_BAD_CREDENTIALS = ("invalid login credentials", "invalid credentials",
                    "invalid grant")
_UNCONFIRMED = ("email not confirmed", "not confirmed")


@dataclass(frozen=True)
class AuthOutcome:
    """A classified result, safe to show a user on a public URL."""

    ok: bool
    message: str
    kind: str          # ok | already_registered | rate_limited | captcha |
                       # bad_credentials | unconfirmed | error
    access_token: str | None = None
    user_id: str | None = None
    user_email: str | None = None


def classify_auth_error(exc: Exception, *, during: str = "signin") -> AuthOutcome:
    """Turn a raw auth exception into a message that does not leak state.

    Sign-up is the sensitive direction: telling an anonymous visitor "that email
    is already registered" turns the endpoint into an account-existence oracle.
    During sign-up we therefore answer uniformly — the legitimate owner gets the
    same instruction to check their inbox either way.

    Sign-in is not sensitive in the same way (the caller already asserts they own
    the account), so "invalid email or password" is correct and more useful
    there.
    """
    text = str(exc)
    low = text.lower()

    if any(s in low for s in _RATE_LIMITED):
        return AuthOutcome(
            ok=False, kind="rate_limited",
            message=("Too many attempts right now. Please wait a few minutes "
                     "and try again."))
    if any(s in low for s in _CAPTCHA_FAILED):
        return AuthOutcome(
            ok=False, kind="captcha",
            message=("The bot-protection check did not pass. Reload the page "
                     "and complete the challenge again."))
    if any(s in low for s in _ALREADY_REGISTERED):
        if during == "signup":
            # Deliberately indistinguishable from success.
            return AuthOutcome(
                ok=True, kind="already_registered",
                message=SIGNUP_UNIFORM_MESSAGE)
        return AuthOutcome(ok=False, kind="already_registered",
                           message="That address is already registered. Try signing in.")
    if any(s in low for s in _BAD_CREDENTIALS):
        return AuthOutcome(ok=False, kind="bad_credentials",
                           message="Incorrect email or password.")
    if any(s in low for s in _UNCONFIRMED):
        return AuthOutcome(
            ok=False, kind="unconfirmed",
            message=("This address still needs confirming. Check your inbox for "
                     "the confirmation link."))
    return AuthOutcome(ok=False, kind="error",
                       message=f"Authentication failed: {text[:200]}")


# --------------------------------------------------------------------------- #
# Auth calls
# --------------------------------------------------------------------------- #

@dataclass
class SignUpResult:
    ok: bool
    message: str
    kind: str
    user_email: str | None = None
    needs_confirmation: bool = False


def sign_up(email: str, password: str, *, captcha_token: str | None = None,
            client: Any | None = None) -> SignUpResult:
    """Create an account.

    ``captcha_token`` is forwarded as ``options.captcha_token``, which
    supabase-auth turns into ``gotrue_meta_security.captcha_token``. Supabase
    verifies it server side — passing ``None`` does not bypass the check when
    the project has CAPTCHA enabled, it simply fails.
    """
    email = (email or "").strip()
    if not email or "@" not in email:
        return SignUpResult(False, "Enter a valid email address.", "error")

    problem = password_problem(password)
    if problem:
        return SignUpResult(False, problem, "error")

    cfg = captcha_config()
    if cfg.enabled and not (captcha_token or "").strip():
        return SignUpResult(
            False, "Complete the bot-protection check, then try again.", "captcha")

    if client is None:
        from database.supabase_client import get_supabase_client
        client = get_supabase_client()

    credentials: dict[str, Any] = {"email": email, "password": password}
    if captcha_token:
        credentials["options"] = {"captcha_token": captcha_token}

    try:
        res = client.auth.sign_up(credentials)
    except Exception as e:                                       # noqa: BLE001
        outcome = classify_auth_error(e, during="signup")
        return SignUpResult(outcome.ok, outcome.message, outcome.kind,
                            user_email=email if outcome.ok else None,
                            needs_confirmation=outcome.ok)

    session = getattr(res, "session", None)
    user = getattr(res, "user", None)
    if session:
        # Only happens when the project has email confirmation switched off.
        return SignUpResult(True, "Account created. You are signed in.",
                            "ok", user_email=getattr(user, "email", email),
                            needs_confirmation=False)
    return SignUpResult(
        True, SIGNUP_UNIFORM_MESSAGE, "ok",
        user_email=getattr(user, "email", email) or email,
        needs_confirmation=True)


def sign_in(email: str, password: str, *, captcha_token: str | None = None,
            client: Any | None = None) -> AuthOutcome:
    """Sign in with password, forwarding the CAPTCHA token when configured."""
    email = (email or "").strip()
    if not email or not password:
        return AuthOutcome(False, "Enter an email and password.", "error")

    cfg = captcha_config()
    if cfg.enabled and not (captcha_token or "").strip():
        return AuthOutcome(False, "Complete the bot-protection check, then "
                                  "try again.", "captcha")

    if client is None:
        from database.supabase_client import get_supabase_client
        client = get_supabase_client()

    credentials: dict[str, Any] = {"email": email, "password": password}
    if captcha_token:
        credentials["options"] = {"captcha_token": captcha_token}

    try:
        res = client.auth.sign_in_with_password(credentials)
    except Exception as e:                                       # noqa: BLE001
        return classify_auth_error(e, during="signin")

    session = getattr(res, "session", None)
    if not session:
        return AuthOutcome(
            False,
            "Sign-in returned no session — is the email confirmed?",
            "unconfirmed")
    user = getattr(res, "user", None)
    return AuthOutcome(True, "Signed in.", "ok",
                       access_token=getattr(session, "access_token", None),
                       user_id=getattr(user, "id", None),
                       user_email=getattr(user, "email", None))
