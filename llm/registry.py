"""Provider registry + model resolver for QuantumCrewBD.

Goal: NO agent ever hardcodes a model. Every agent asks the resolver for its
``LLMConfig``, so swapping provider/model is a configuration change, never a
code change.

Precedence (highest wins) — see ``resolve()``:
  1. explicit per-call override        resolve(agent="analyst", overrides={...})
  2. per-tenant setting (DB, phase 2)  injected by the caller as ``settings``
  3. environment ``LLM_MODEL_<AGENT>`` e.g. LLM_MODEL_ANALYST
  4. environment ``LLM_MODEL``         global default
  5. registry default for the provider

Verified facts baked in (see docs/04-Reference/llm-providers.md):
  * CrewAI 1.15.23 has no native groq/deepseek provider: EVERYTHING routes
    through its OpenAI-compatible path, which requires the ``openai/`` model
    prefix. So crewai_model == "openai/" + model_id.
  * Both Groq and CommandCode sit behind Cloudflare and reject non-browser
    User-Agents with HTTP 403 / error 1010.
  * Groq's free tier is 8000 TPM -> a full tender (~23k tokens) returns
    HTTP 413. Providers that need chunking declare ``max_prompt_tokens``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

# --- Provider definitions -------------------------------------------------

#: CrewAI routes every non-native provider through its OpenAI-compatible path,
#: which prefixes the model with ``openai/``. Not a per-provider choice today,
#: but kept as a field so a native provider can opt out later.
_OPENAI_COMPAT_PREFIX = "openai/"

#: Sent with every request. Both upstreams reject non-browser agents (CF 1010).
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class ModelSpec:
    """One selectable model. ``id`` is the provider's own identifier."""

    id: str
    context_tokens: int = 128_000
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0
    supports_tools: bool = True
    #: Peak-hour multiplier (DeepSeek charges 2x during peak windows).
    peak_multiplier: float = 1.0

    def crewai_model(self) -> str:
        """Model string CrewAI must receive (prefix included)."""
        return f"{_OPENAI_COMPAT_PREFIX}{self.id}"


@dataclass(frozen=True)
class Provider:
    """An OpenAI-compatible LLM endpoint."""

    name: str
    base_url: str
    api_key_env: str
    models: dict[str, ModelSpec] = field(default_factory=dict)
    default_model: str = ""
    #: None = no chunking needed. Int (tokens) = hard per-request ceiling.
    max_prompt_tokens: int | None = None
    notes: str = ""

    def get(self, alias: str) -> ModelSpec:
        try:
            return self.models[alias]
        except KeyError:
            raise KeyError(
                f"unknown model alias {alias!r} for provider {self.name!r}; "
                f"known: {sorted(self.models)}"
            ) from None


# --- The registry ---------------------------------------------------------
# CommandCode ids verified live via GET /provider/v1/models on 2026-10-03.

GROQ = Provider(
    name="groq",
    base_url="https://api.groq.com/openai/v1",
    api_key_env="GROQ_API_KEY",
    default_model="gpt-oss-120b",
    # Free tier: 8000 tokens/minute. A 23k-token tender is an instant 413.
    max_prompt_tokens=8_000,
    notes="free tier = 8000 TPM; full tenders MUST be chunked",
    models={
        "gpt-oss-120b": ModelSpec(
            id="openai/gpt-oss-120b",  # note: 'openai/' is part of Groq's own id
            context_tokens=131_072,
        ),
    },
)

COMMANDCODE = Provider(
    name="commandcode",
    base_url="https://api.commandcode.ai/provider/v1",
    api_key_env="COMMANDCODE_API_KEY",
    default_model="deepseek-v4.1-flash-fast",
    max_prompt_tokens=None,  # took a 23k-token tender in one call, 1.7s
    notes="Cloudflare-fronted; pay-as-you-go, no markup",
    models={
        # --- DeepSeek family (all 3/3 correct on the DOC-3 extraction probe) ---
        "deepseek-v4.1-flash-fast": ModelSpec(
            id="deepseek/deepseek-v4.1-flash",
            context_tokens=1_000_000,
            input_usd_per_mtok=0.16,
            output_usd_per_mtok=0.58,
            peak_multiplier=2.0,
        ),
        "deepseek-v4.1-flash": ModelSpec(
            id="deepseek/deepseek-v4.1-flash",
            context_tokens=1_000_000,
            input_usd_per_mtok=0.15,
            output_usd_per_mtok=0.60,
            peak_multiplier=2.0,
        ),
        "deepseek-v4-flash": ModelSpec(
            id="deepseek/deepseek-v4-flash",
            context_tokens=1_000_000,
            input_usd_per_mtok=0.15,
            output_usd_per_mtok=0.60,
            peak_multiplier=2.0,
        ),
        "deepseek-v4-pro": ModelSpec(
            id="deepseek/deepseek-v4-pro",
            context_tokens=1_000_000,
            input_usd_per_mtok=0.66,
            output_usd_per_mtok=1.98,
            peak_multiplier=2.0,
        ),
        # --- Cheaper alternatives (verified tool-calling + correct on DOC-3) ---
        "gpt-6-luna": ModelSpec(
            id="gpt-6-luna",
            context_tokens=1_100_000,
            input_usd_per_mtok=0.10,
            output_usd_per_mtok=0.50,
        ),
        "mimo-v2.6-pro": ModelSpec(
            id="xiaomi/mimo-v2.6-pro",
            context_tokens=1_000_000,
            input_usd_per_mtok=0.435,
            output_usd_per_mtok=0.87,
        ),
    },
)

PROVIDERS: dict[str, Provider] = {p.name: p for p in (COMMANDCODE, GROQ)}

#: Applied when nothing else is configured. User decision 2026-10-03.
DEFAULT_PROVIDER = "commandcode"
DEFAULT_MODEL_ALIAS = "deepseek-v4.1-flash-fast"

#: Per-agent overrides. Empty value => fall through to the global default.
#: Keyed by agent name (lowercase). Populate when tiering is wanted, e.g.
#:   "writer": "mimo-v2.6-pro",
#:   "extractor": "gpt-6-luna",
AGENT_MODEL_DEFAULTS: dict[str, str] = {}

#: Names of the agents in the crew, for UI discovery / validation.
KNOWN_AGENTS: tuple[str, ...] = (
    "analyst",
    "extractor",
    "compliance",
    "market_intel",
    "consortium",
    "writer",
    "reviewer",
)


# --- Resolution -----------------------------------------------------------


@dataclass(frozen=True)
class LLMConfig:
    """Everything needed to construct a CrewAI LLM (minus the key value)."""

    provider: str
    model_alias: str
    model: str  # provider's own id
    crewai_model: str  # what CrewAI receives (prefixed)
    base_url: str
    api_key_env: str
    needs_browser_user_agent: bool
    max_prompt_tokens: int | None
    temperature: float = 0.0

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


def _clean(value: object) -> str | None:
    """Return a stripped string, or None for falsy/blank/placeholder values."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "default", "-"}:
        return None
    return text


def resolve(
    agent: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    overrides: dict[str, str] | None = None,
    settings: dict[str, str] | None = None,
    temperature: float | None = None,
    env: dict[str, str] | None = None,
) -> LLMConfig:
    """Resolve the effective LLM config for ``agent``.

    ``model`` accepts either a registry alias (``deepseek-v4.1-flash-fast``) or
    a raw provider model id (``deepseek/deepseek-v4.1-flash``) for ids that
    aren't in the registry yet — the admin page can add arbitrary models.
    """
    env_map = os.environ if env is None else env
    overrides = overrides or {}
    settings = settings or {}
    key = (agent or "").strip().lower()

    # 1..5 — pick the model alias, first match wins.
    alias = next(
        (
            candidate
            for candidate in (
                _clean(model),                                   # 1 call site
                _clean(overrides.get(key)) if key else None,     # 2 override
                _clean(settings.get(key)) if key else None,      # 3 tenant/DB
                _clean(env_map.get(f"LLM_MODEL_{key.upper()}")) if key else None,
                _clean(AGENT_MODEL_DEFAULTS.get(key)) if key else None,  # per-agent
                _clean(env_map.get("LLM_MODEL")),                # 4 global env
                DEFAULT_MODEL_ALIAS,                             # 5 fallback
            )
            if candidate
        ),
        DEFAULT_MODEL_ALIAS,
    )

    # Provider: explicit > env > global default.
    prov_name = (
        _clean(provider)
        or _clean(env_map.get("LLM_PROVIDER"))
        or DEFAULT_PROVIDER
    )
    if prov_name not in PROVIDERS:
        raise KeyError(f"unknown provider {prov_name!r}; known: {sorted(PROVIDERS)}")
    prov = PROVIDERS[prov_name]

    if alias in prov.models:
        spec = prov.get(alias)
    else:
        # Treat as a raw provider model id (admin-supplied).
        spec = ModelSpec(id=alias)

    return LLMConfig(
        provider=prov.name,
        model_alias=alias,
        model=spec.id,
        crewai_model=spec.crewai_model(),
        base_url=prov.base_url,
        api_key_env=prov.api_key_env,
        needs_browser_user_agent=True,
        max_prompt_tokens=prov.max_prompt_tokens,
        temperature=0.0 if temperature is None else temperature,
    )


def list_models(provider: str | None = None) -> list[dict[str, object]]:
    """Model catalog for the admin configuration UI."""
    names = [provider] if provider else list(PROVIDERS)
    out: list[dict[str, object]] = []
    for name in names:
        prov = PROVIDERS[name]
        for alias, spec in prov.models.items():
            out.append({
                "provider": name,
                "alias": alias,
                "model_id": spec.id,
                "context_tokens": spec.context_tokens,
                "input_usd_per_mtok": spec.input_usd_per_mtok,
                "output_usd_per_mtok": spec.output_usd_per_mtok,
                "supports_tools": spec.supports_tools,
                "is_provider_default": alias == prov.default_model,
            })
    return out
