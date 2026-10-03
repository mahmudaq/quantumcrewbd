"""
QuantumCrewBD — Supabase access layer.

Two distinct access modes, and choosing the wrong one is a silent-failure bug.
Read this before adding a query anywhere in the codebase.

--------------------------------------------------------------------------
WHY THIS MODULE EXISTS  (defect R-04 in the E2E development plan)
--------------------------------------------------------------------------
Every tenant table is protected by row-level security:

    USING      (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id)

`auth.uid()` is resolved from the JWT attached to the PostgREST request. If the
request carries only the **anon** key, there is no user session, so `auth.uid()`
returns NULL, `NULL = user_id` is NULL (not TRUE), and the policy denies.

The failure mode is the dangerous part: **it does not raise.** It returns an
empty result set. An agent tool that searches the internal talent bench would
conclude "no matching CVs" and fall through to external candidate discovery,
producing a plausible-but-wrong proposal with no error anywhere in the logs.

Therefore:

    get_supabase_client()              -> anonymous. AUTH OPERATIONS ONLY.
    get_user_client(access_token)      -> RLS-scoped. ALL DATA OPERATIONS.

Any data read or write that must respect tenant isolation goes through
`get_user_client()`. There is no "convenience" anon path for data.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------
    from database.supabase_client import get_supabase_client, get_user_client

    anon = get_supabase_client()
    anon.auth.sign_in_with_password({"email": ..., "password": ...})

    user = get_user_client(session.access_token)
    user.table("team_cvs").select("*").execute()      # RLS applied
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

# Environment variable names. Streamlit Community Cloud supplies these through
# its secrets UI, which is surfaced into the process environment — hence plain
# os.environ rather than st.secrets, so this module stays usable from tests and
# from a headless CLI run.
ENV_URL = "SUPABASE_URL"
ENV_ANON_KEY = "SUPABASE_ANON_KEY"

# Legacy alias — the Supabase dashboard labels this key "anon" in older
# projects and "publishable" in newer ones. Accept both so a project rename
# doesn't silently break startup.
ENV_ANON_KEY_ALIASES = ("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY")

_anon_client: Client | None = None
_lock = Lock()


class SupabaseConfigError(RuntimeError):
    """Raised when required Supabase configuration is absent or malformed."""


def _read_env(*names: str) -> str | None:
    """Return the first non-empty value among `names`, or None."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _require_config() -> tuple[str, str]:
    url = _read_env(ENV_URL)
    key = _read_env(*ENV_ANON_KEY_ALIASES)

    missing = [
        name
        for name, value in ((ENV_URL, url), ("SUPABASE_ANON_KEY", key))
        if not value
    ]
    if missing or url is None or key is None:
        raise SupabaseConfigError(
            "Missing Supabase configuration: "
            + ", ".join(missing or ["<unknown>"])
            + ". Set these in the environment (or in Streamlit Community Cloud's "
            "secrets UI). Run `cp .env.example .env` for local development."
        )

    if not url.startswith(("http://", "https://")):
        raise SupabaseConfigError(
            f"{ENV_URL} must be a full URL including scheme, got: {url!r}"
        )

    return url, key


def get_supabase_client() -> Client:
    """
    Anonymous client, memoised.

    Use ONLY for authentication calls — sign_up, sign_in_with_password,
    refresh_session, sign_out, reset_password_for_email. Never for reading or
    writing tenant data: with no user session the RLS policies deny everything
    and you will get an empty result rather than an error (see module docstring).
    """
    global _anon_client
    if _anon_client is not None:
        return _anon_client

    with _lock:
        # Re-check inside the lock: two Streamlit reruns can race here.
        if _anon_client is None:
            url, key = _require_config()
            _anon_client = create_client(url, key)

    return _anon_client


def get_user_client(access_token: str) -> Client:
    """
    RLS-scoped client. This is the correct client for all data access.

    Builds a fresh client and attaches `access_token` (a Supabase user JWT) to
    the PostgREST layer, so `auth.uid()` inside the RLS policies resolves to
    that user and tenant isolation is enforced by the database rather than by
    application code.

    Deliberately NOT memoised: a cached client keyed to a stale JWT would leak
    one user's tenant scope into another user's session after logout or
    re-login. The construction cost is negligible.

    Raises:
        ValueError: if `access_token` is empty — a missing token means a bug in
            the caller's session handling, and failing loudly here prevents
            silently degrading to anonymous access.
    """
    if not access_token or not access_token.strip():
        raise ValueError(
            "get_user_client() requires a non-empty Supabase access token. "
            "An empty token would silently degrade to anonymous access and "
            "return zero rows under RLS."
        )

    url, key = _require_config()
    client = create_client(url, key)
    client.postgrest.auth(access_token.strip())
    return client


def get_session_from_client(client: Client) -> Any:
    """
    Return the current auth session from a client, or None.

    `client.auth.get_session()` raises on some supabase-py versions when no
    session is set; normalise that to None so callers can branch cleanly.
    """
    try:
        return client.auth.get_session()
    except Exception:
        return None


def reset_client_cache() -> None:
    """Drop the memoised anonymous client. Tests and credential rotation use this."""
    global _anon_client
    with _lock:
        _anon_client = None
