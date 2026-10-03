"""Tests for the LLM provider registry and resolver.

The point of this module is that model choice is *configuration*, so the tests
are mostly about precedence: which setting wins when several are present.
"""

from __future__ import annotations

import pytest

from llm.registry import (
    DEFAULT_MODEL_ALIAS,
    DEFAULT_PROVIDER,
    PROVIDERS,
    list_models,
    resolve,
)

EMPTY_ENV: dict[str, str] = {}


class TestResolveDefaults:
    def test_falls_back_to_the_chosen_default_model(self):
        cfg = resolve(env=EMPTY_ENV)
        assert cfg.provider == DEFAULT_PROVIDER == "commandcode"
        assert cfg.model_alias == DEFAULT_MODEL_ALIAS == "deepseek-v4.1-flash-fast"

    def test_default_model_is_the_deepseek_41_flash_family(self):
        cfg = resolve(env=EMPTY_ENV)
        assert "deepseek-v4.1-flash" in cfg.model

    def test_crewai_model_carries_the_openai_prefix(self):
        """CrewAI's OpenAI-compatible path requires the prefix (verified live)."""
        cfg = resolve(env=EMPTY_ENV)
        assert cfg.crewai_model == f"openai/{cfg.model}"

    def test_commandcode_base_url_is_the_provider_path(self):
        """Not /v1 — the provider API lives under /provider/v1."""
        cfg = resolve(env=EMPTY_ENV)
        assert cfg.base_url == "https://api.commandcode.ai/provider/v1"

    def test_every_agent_resolves_by_default(self):
        from llm.registry import KNOWN_AGENTS

        for agent in KNOWN_AGENTS:
            cfg = resolve(agent=agent, env=EMPTY_ENV)
            assert cfg.model_alias == DEFAULT_MODEL_ALIAS

    def test_known_agents_matches_the_real_agent_modules(self):
        """The registry list and agents/__init__.py must not drift.

        The per-agent model override (``LLM_MODEL_<AGENT>``) and the admin
        config UI both key off these exact strings. When the list held phantom
        names — "analyst"/"extractor"/"compliance"/"consortium" — a user could
        set a model for "analyzer" and the system would silently ignore it,
        because "analyzer" was not a recognised key.
        """
        import agents
        from llm.registry import KNOWN_AGENTS

        assert set(KNOWN_AGENTS) == set(agents.__all__), (
            f"registry {sorted(KNOWN_AGENTS)} != modules {sorted(agents.__all__)}"
        )
        assert len(KNOWN_AGENTS) == len(set(KNOWN_AGENTS)), "duplicate agent name"

    def test_per_agent_override_actually_changes_that_agents_model(self):
        """The regression, at the level the user experiences it.

        Setting LLM_MODEL_ANALYZER must change the analyzer's model and leave
        the other agents alone.
        """
        env = {"LLM_MODEL_ANALYZER": "gpt-oss-120b"}
        assert resolve(agent="analyzer", env=env).model_alias == "gpt-oss-120b"
        assert resolve(agent="writer", env=env).model_alias == DEFAULT_MODEL_ALIAS

    def test_every_real_agent_name_is_override_honoured(self):
        """No real agent may be silently un-overridable."""
        import agents

        for name in agents.__all__:
            env = {f"LLM_MODEL_{name.upper()}": "gpt-oss-120b"}
            got = resolve(agent=name, env=env).model_alias
            assert got == "gpt-oss-120b", f"{name} ignored its per-agent override"


class TestPrecedence:
    def test_explicit_model_beats_everything(self):
        cfg = resolve(
            agent="writer",
            model="mimo-v2.6-pro",
            overrides={"writer": "deepseek-v4-pro"},
            settings={"writer": "gpt-6-luna"},
            env={"LLM_MODEL_WRITER": "deepseek-v4-flash", "LLM_MODEL": "deepseek-v4-flash"},
        )
        assert cfg.model_alias == "mimo-v2.6-pro"

    def test_override_beats_tenant_setting_and_env(self):
        cfg = resolve(
            agent="writer",
            overrides={"writer": "mimo-v2.6-pro"},
            settings={"writer": "gpt-6-luna"},
            env={"LLM_MODEL_WRITER": "deepseek-v4-flash"},
        )
        assert cfg.model_alias == "mimo-v2.6-pro"

    def test_tenant_setting_beats_env(self):
        cfg = resolve(
            agent="writer",
            settings={"writer": "gpt-6-luna"},
            env={"LLM_MODEL_WRITER": "deepseek-v4-flash"},
        )
        assert cfg.model_alias == "gpt-6-luna"

    def test_per_agent_env_beats_global_env(self):
        cfg = resolve(
            agent="writer",
            env={"LLM_MODEL_WRITER": "gpt-6-luna", "LLM_MODEL": "deepseek-v4-flash"},
        )
        assert cfg.model_alias == "gpt-6-luna"

    def test_global_env_beats_builtin_default(self):
        cfg = resolve(env={"LLM_MODEL": "gpt-6-luna"})
        assert cfg.model_alias == "gpt-6-luna"

    def test_overrides_are_per_agent_not_global(self):
        cfg = resolve(agent="writer", overrides={"analyst": "gpt-6-luna"}, env=EMPTY_ENV)
        assert cfg.model_alias == DEFAULT_MODEL_ALIAS


class TestPlaceholderHandling:
    @pytest.mark.parametrize("blank", ["", "   ", "none", "None", "NULL", "default", "-"])
    def test_blank_placeholders_fall_through(self, blank):
        """Streamlit/env vars often hold '' or 'default' — must not stick."""
        cfg = resolve(model=blank, env=EMPTY_ENV)
        assert cfg.model_alias == DEFAULT_MODEL_ALIAS

    def test_blank_per_agent_override_falls_through_to_global(self):
        cfg = resolve(agent="writer", env={"LLM_MODEL_WRITER": "  ", "LLM_MODEL": "gpt-6-luna"})
        assert cfg.model_alias == "gpt-6-luna"


class TestProviderSwitching:
    def test_can_switch_to_groq_without_code_changes(self):
        cfg = resolve(provider="groq", model="gpt-oss-120b", env=EMPTY_ENV)
        assert cfg.provider == "groq"
        assert cfg.base_url == "https://api.groq.com/openai/v1"
        assert cfg.api_key_env == "GROQ_API_KEY"

    def test_provider_can_come_from_env(self):
        cfg = resolve(env={"LLM_PROVIDER": "groq"})
        assert cfg.provider == "groq"

    def test_groq_declares_its_chunking_ceiling(self):
        """Free tier is 8000 TPM; a full tender is an instant HTTP 413."""
        cfg = resolve(provider="groq", model="gpt-oss-120b", env=EMPTY_ENV)
        assert cfg.max_prompt_tokens == 8_000

    def test_commandcode_needs_no_chunking(self):
        cfg = resolve(env=EMPTY_ENV)
        assert cfg.max_prompt_tokens is None

    def test_groq_model_keeps_its_own_openai_prefix(self):
        """Groq's real id is 'openai/gpt-oss-120b' -> double prefix for CrewAI."""
        cfg = resolve(provider="groq", model="gpt-oss-120b", env=EMPTY_ENV)
        assert cfg.crewai_model == "openai/openai/gpt-oss-120b"

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(KeyError, match="unknown provider"):
            resolve(provider="not-a-provider", env=EMPTY_ENV)

    def test_unknown_model_alias_is_treated_as_raw_id(self):
        """Lets admins paste a brand-new provider model id before we catalogue it."""
        cfg = resolve(model="some/new-model", env=EMPTY_ENV)
        assert cfg.model == "some/new-model"
        assert cfg.crewai_model == "openai/some/new-model"


class TestAdminCatalog:
    def test_lists_models_for_the_ui(self):
        rows = list_models()
        assert rows, "catalog must not be empty"
        assert {"provider", "alias", "model_id", "context_tokens"} <= set(rows[0])

    def test_includes_the_default_model(self):
        aliases = {r["alias"] for r in list_models()}
        assert DEFAULT_MODEL_ALIAS in aliases

    def test_includes_the_cheaper_tier_alternatives(self):
        aliases = {r["alias"] for r in list_models()}
        assert {"gpt-6-luna", "mimo-v2.6-pro"} <= aliases

    def test_can_filter_by_provider(self):
        assert {r["provider"] for r in list_models("groq")} == {"groq"}

    def test_groq_is_retained_as_a_fallback_option(self):
        assert PROVIDERS["groq"].default_model == "gpt-oss-120b"


class TestCostMetadata:
    def test_deepseek_declares_peak_multiplier(self):
        """Peak surcharge hits 06:00-09:00 and 11:00-15:00 PKT."""
        cfg = resolve(env=EMPTY_ENV)
        spec = PROVIDERS["commandcode"].get(cfg.model_alias)
        assert spec.peak_multiplier == 2.0

    def test_gpt_6_luna_has_no_peak_surcharge(self):
        spec = PROVIDERS["commandcode"].get("gpt-6-luna")
        assert spec.peak_multiplier == 1.0
