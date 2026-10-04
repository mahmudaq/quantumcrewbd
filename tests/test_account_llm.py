"""Tests for per-account LLM configuration and its encryption at rest.

Three things are being pinned down here:

1. The key is stored ENCRYPTED. A regression that writes plaintext would be
   invisible in the UI, so the assertion is explicit.
2. A missing/wrong ``QC_SECRET_KEY`` degrades to "no key configured" instead of
   crashing the page — a demo must not die because the env var was dropped.
3. The account's provider/model actually reaches ``resolve()``. The pre-existing
   per-account selector did NOT (it wrote ``{"provider","model"}`` while
   ``resolve()`` only read ``overrides["<agent>"]``), and nothing caught it
   because no test asserted the override took effect.

No live database is used: ``FakeClient`` mimics the two supabase-py chains this
module needs (``select().eq().limit().execute()`` and ``update().eq().execute()``).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from llm.account_keys import (
    MissingSecretKeyError,
    decrypt_api_key,
    encrypt_api_key,
    load_account_llm,
    save_account_llm,
)
from llm.client import build_llm
from llm.registry import resolve

SECRET = Fernet.generate_key().decode()
OTHER_SECRET = Fernet.generate_key().decode()
PLAINTEXT = "user_2wSexamplekeyvalue123"


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Records the chain, returns `data`. Mirrors supabase-py's shape."""

    def __init__(self, table):
        self._table = table
        self.op = None
        self.payload = None

    def select(self, *cols, **kw):
        self.op = "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, col, val):
        self._table.queries.append((self.op, col, val, self.payload))
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self.op == "select":
            return FakeResult(self._table.select_rows)
        self._table.rows.append(self.payload or {})
        return FakeResult([self.payload])


class FakeTable:
    def __init__(self, select_rows=None):
        self.select_rows = select_rows if select_rows is not None else []
        self.rows: list[dict] = []
        self.queries: list[tuple] = []

    def select(self, *a, **k):
        return FakeQuery(self).select(*a, **k)

    def update(self, payload):
        return FakeQuery(self).update(payload)


class FakeClient:
    def __init__(self, select_rows=None):
        self.table_obj = FakeTable(select_rows)

    def table(self, name):
        self.name = name
        return self.table_obj


# --------------------------------------------------------------------------- #
# Encryption at rest
# --------------------------------------------------------------------------- #

class TestEncryption:
    def test_round_trips_a_key(self):
        token = encrypt_api_key(PLAINTEXT, secret=SECRET)
        assert decrypt_api_key(token, secret=SECRET) == PLAINTEXT

    def test_ciphertext_does_not_contain_the_plaintext(self):
        token = encrypt_api_key(PLAINTEXT, secret=SECRET)
        assert PLAINTEXT not in token

    def test_two_encryptions_of_the_same_key_differ(self):
        # Fernet embeds a random IV: identical plaintext must not produce
        # identical ciphertext, or the column leaks equality between accounts.
        assert encrypt_api_key(PLAINTEXT, secret=SECRET) != encrypt_api_key(
            PLAINTEXT, secret=SECRET
        )

    def test_wrong_secret_raises_a_clear_error(self):
        token = encrypt_api_key(PLAINTEXT, secret=SECRET)
        with pytest.raises(ValueError, match="QC_SECRET_KEY"):
            decrypt_api_key(token, secret=OTHER_SECRET)

    def test_empty_key_is_refused(self):
        with pytest.raises(ValueError, match="empty"):
            encrypt_api_key("", secret=SECRET)
        with pytest.raises(ValueError, match="empty"):
            encrypt_api_key("   ", secret=SECRET)

    def test_missing_secret_is_reported_by_name(self, monkeypatch):
        monkeypatch.delenv("QC_SECRET_KEY", raising=False)
        with pytest.raises(MissingSecretKeyError, match="QC_SECRET_KEY"):
            encrypt_api_key(PLAINTEXT)

    def test_malformed_secret_is_reported_not_a_crash(self):
        with pytest.raises(MissingSecretKeyError, match="valid Fernet"):
            encrypt_api_key(PLAINTEXT, secret="not-a-fernet-key")


# --------------------------------------------------------------------------- #
# load / save
# --------------------------------------------------------------------------- #

class TestLoad:
    def test_reads_provider_model_and_decrypts_the_key(self):
        token = encrypt_api_key(PLAINTEXT, secret=SECRET)
        client = FakeClient([{
            "llm_provider": "commandcode",
            "llm_model": "deepseek/deepseek-v4.1-flash-fast",
            "llm_api_key_enc": token,
        }])
        cfg = load_account_llm(client, "user-1", secret=SECRET)
        assert cfg["provider"] == "commandcode"
        assert cfg["model"] == "deepseek/deepseek-v4.1-flash-fast"
        assert cfg["api_key"] == PLAINTEXT

    def test_never_returns_the_ciphertext_as_the_key(self):
        token = encrypt_api_key(PLAINTEXT, secret=SECRET)
        client = FakeClient([{"llm_api_key_enc": token}])
        cfg = load_account_llm(client, "user-1", secret=SECRET)
        # The ciphertext must never be handed out as if it were the key.
        assert cfg["api_key"] == PLAINTEXT
        assert cfg["api_key"] != token

    def test_undecryptable_key_degrades_instead_of_raising(self, monkeypatch):
        # Simulates a redeploy with a different QC_SECRET_KEY.
        token = encrypt_api_key(PLAINTEXT, secret=OTHER_SECRET)
        monkeypatch.setenv("QC_SECRET_KEY", SECRET)
        cfg = load_account_llm(FakeClient([{"llm_api_key_enc": token}]), "user-1")
        assert cfg["api_key"] is None
        assert "re-enter" in cfg["key_error"]

    def test_missing_profile_row_yields_empty_config(self):
        assert load_account_llm(FakeClient([]), "user-1") == {}

    def test_no_client_or_user_is_an_empty_config(self):
        assert load_account_llm(None, "user-1") == {}
        assert load_account_llm(FakeClient([]), "") == {}

    def test_a_failing_query_does_not_propagate(self):
        class Boom:
            def table(self, _name):
                raise RuntimeError("network down")

        assert load_account_llm(Boom(), "user-1") == {}


class TestSave:
    def test_stores_ciphertext_not_plaintext(self):
        client = FakeClient()
        save_account_llm(client, "user-1", api_key=PLAINTEXT, secret=SECRET)
        written = client.table_obj.rows[-1]
        assert "llm_api_key_enc" in written
        assert PLAINTEXT not in written["llm_api_key_enc"]
        assert decrypt_api_key(written["llm_api_key_enc"], secret=SECRET) == PLAINTEXT

    def test_none_key_leaves_the_stored_key_untouched(self):
        client = FakeClient()
        save_account_llm(client, "user-1", provider="groq", model="m", secret=SECRET)
        written = client.table_obj.rows[-1]
        assert "llm_api_key_enc" not in written

    def test_empty_string_clears_the_stored_key(self):
        client = FakeClient()
        save_account_llm(client, "user-1", api_key="", secret=SECRET)
        assert client.table_obj.rows[-1]["llm_api_key_enc"] is None

    def test_updates_the_row_for_this_user_only(self):
        client = FakeClient()
        save_account_llm(client, "user-42", api_key=PLAINTEXT, secret=SECRET)
        op, col, val, _payload = client.table_obj.queries[-1]
        assert (op, col, val) == ("update", "id", "user-42")

    def test_nothing_to_save_writes_nothing(self):
        client = FakeClient()
        assert save_account_llm(client, "user-1") == {}
        assert client.table_obj.rows == []


# --------------------------------------------------------------------------- #
# The override must actually reach the resolver
# --------------------------------------------------------------------------- #

class TestAccountOverrideReachesResolver:
    def test_account_model_override_is_honoured(self):
        base = resolve(agent="analyzer", env={})
        cfg = resolve(agent="analyzer",
                      overrides={"provider": "groq", "model": "llama-3.3-70b-versatile"},
                      env={})
        assert cfg.provider == "groq"
        assert cfg.model == "llama-3.3-70b-versatile"
        assert cfg.model != base.model

    def test_account_provider_override_is_honoured(self):
        cfg = resolve(agent="analyzer", overrides={"provider": "groq"}, env={})
        assert cfg.provider == "groq"

    def test_agent_keyed_override_still_wins_for_its_agent(self):
        # The pre-existing per-agent override must not regress.
        cfg = resolve(agent="writer",
                      overrides={"writer": "llama-3.3-70b-versatile"}, env={})
        assert cfg.model == "llama-3.3-70b-versatile"

    def test_settings_can_carry_the_account_choice_too(self):
        cfg = resolve(agent="analyzer", settings={"provider": "groq"}, env={})
        assert cfg.provider == "groq"

    def test_explicit_call_argument_beats_the_account_override(self):
        cfg = resolve(agent="analyzer", provider="commandcode",
                      overrides={"provider": "groq"}, env={})
        assert cfg.provider == "commandcode"


# --------------------------------------------------------------------------- #
# build_llm: the key the pipeline carried down in `settings`
# --------------------------------------------------------------------------- #

class TestBuildLlmKeyResolution:
    """``build_llm`` never constructs a real LLM — a fake class records kwargs."""

    @pytest.fixture
    def fake_crewai(self, monkeypatch):
        captured: dict = {}

        class FakeLLM:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        import crewai
        monkeypatch.setattr(crewai, "LLM", FakeLLM, raising=True)
        return captured

    def test_key_from_settings_is_used(self, fake_crewai, monkeypatch):
        monkeypatch.delenv("COMMANDCODE_API_KEY", raising=False)
        build_llm(agent="analyzer", provider="commandcode",
                  settings={"api_key": "sk-from-account"})
        assert fake_crewai["api_key"] == "sk-from-account"

    def test_explicit_key_argument_beats_settings(self, fake_crewai):
        build_llm(agent="analyzer", provider="commandcode",
                  api_key="sk-explicit", settings={"api_key": "sk-account"})
        assert fake_crewai["api_key"] == "sk-explicit"

    def test_settings_key_beats_the_environment(self, fake_crewai, monkeypatch):
        monkeypatch.setenv("COMMANDCODE_API_KEY", "sk-env")
        build_llm(agent="analyzer", provider="commandcode",
                  settings={"api_key": "sk-account"})
        assert fake_crewai["api_key"] == "sk-account"

    def test_environment_still_works_when_no_account_key(self, fake_crewai, monkeypatch):
        monkeypatch.setenv("COMMANDCODE_API_KEY", "sk-env")
        build_llm(agent="analyzer", provider="commandcode")
        assert fake_crewai["api_key"] == "sk-env"

    def test_no_key_anywhere_still_raises(self, fake_crewai, monkeypatch):
        monkeypatch.delenv("COMMANDCODE_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        from llm.client import MissingAPIKeyError
        with pytest.raises(MissingAPIKeyError):
            build_llm(agent="analyzer", provider="commandcode")
