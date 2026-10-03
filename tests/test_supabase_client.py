"""Unit tests for the Supabase access layer — no network required.

These cover the configuration and session-boundary logic that defect R-04 makes
load-bearing: the distinction between an anonymous client (auth only) and a
user-scoped client (all data access).
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from database import supabase_client as sc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Isolate each test from ambient Supabase config, and reset the memo."""
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY",
                 "SUPABASE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    sc.reset_client_cache()
    yield
    sc.reset_client_cache()


def test_user_client_rejects_empty_token():
    """An empty token must raise, never silently degrade to anonymous access."""
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            sc.get_user_client(bad)  # type: ignore[arg-type]


def test_user_client_attaches_token_to_postgrest():
    """The token must reach the PostgREST layer, which is what populates auth.uid()."""
    with mock.patch.object(sc, "create_client") as create:
        client = create.return_value
        sc.get_user_client("jwt-abc.123")

    client.postgrest.auth.assert_called_once_with("jwt-abc.123")


def test_user_client_is_not_memoised():
    """A cached user client would leak one tenant's scope into another session."""
    with mock.patch.object(sc, "create_client") as create:
        # Distinct objects per call — otherwise MagicMock's shared return_value
        # makes the identity assertion vacuous.
        create.side_effect = lambda *a, **k: mock.Mock()
        c1 = sc.get_user_client("token-one")
        c2 = sc.get_user_client("token-one")

    assert c1 is not c2
    assert create.call_count == 2


def test_each_user_client_gets_its_own_token():
    """Two different users must never share a PostgREST auth context."""
    with mock.patch.object(sc, "create_client") as create:
        create.side_effect = lambda *a, **k: mock.Mock()
        a = sc.get_user_client("token-user-a")
        b = sc.get_user_client("token-user-b")

    a.postgrest.auth.assert_called_once_with("token-user-a")
    b.postgrest.auth.assert_called_once_with("token-user-b")


def test_anon_client_is_memoised():
    with mock.patch.object(sc, "create_client") as create:
        assert sc.get_supabase_client() is sc.get_supabase_client()

    assert create.call_count == 1


def test_missing_url_raises_config_error(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    sc.reset_client_cache()

    with pytest.raises(sc.SupabaseConfigError) as exc:
        sc.get_supabase_client()

    assert "SUPABASE_URL" in str(exc.value)


def test_missing_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    sc.reset_client_cache()

    with pytest.raises(sc.SupabaseConfigError) as exc:
        sc.get_supabase_client()

    assert "SUPABASE_ANON_KEY" in str(exc.value)


def test_publishable_key_alias_is_accepted(monkeypatch):
    """Newer Supabase projects label the anon key 'publishable'."""
    monkeypatch.delenv("SUPABASE_ANON_KEY")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_xyz")
    sc.reset_client_cache()

    with mock.patch.object(sc, "create_client") as create:
        sc.get_supabase_client()

    assert create.call_args[0][1] == "sb_publishable_xyz"


def test_url_without_scheme_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "example.supabase.co")
    sc.reset_client_cache()

    with pytest.raises(sc.SupabaseConfigError):
        sc.get_supabase_client()


def test_get_session_returns_none_when_absent():
    """supabase-py raises on a session-less client; normalise that to None."""
    client = mock.Mock()
    client.auth.get_session.side_effect = Exception("no session")

    assert sc.get_session_from_client(client) is None
