"""Build CrewAI ``LLM`` objects from resolved configuration.

Kept separate from :mod:`llm.registry` so the registry stays importable (and
testable) without pulling in CrewAI or the network stack.

Two upstream quirks are handled here so no agent ever has to know about them:

1. **Model prefix** — CrewAI's OpenAI-compatible path requires ``openai/`` in
   front of the model id, and the resolver already supplies it.
2. **Cloudflare** — both Groq and CommandCode reject non-browser User-Agents
   with HTTP 403 / error 1010, so a browser UA is injected into the HTTP client
   CrewAI uses under the hood.
"""

from __future__ import annotations

import os
from typing import Any

from llm.registry import BROWSER_USER_AGENT, LLMConfig, resolve


class MissingAPIKeyError(RuntimeError):
    """Raised when the selected provider's API key is not set."""


def _install_browser_user_agent() -> None:
    """Patch the OpenAI client used by CrewAI to send a browser User-Agent.

    Idempotent. ``default_headers`` is the documented hook; if CrewAI changes
    internals the call still works, it just won't carry the UA.
    """
    try:
        import openai
    except ImportError:  # pragma: no cover - openai ships with crewai
        return

    if getattr(openai.OpenAI, "_qcb_ua_patched", False):
        return

    original_init = openai.OpenAI.__init__

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        headers = dict(kwargs.get("default_headers") or {})
        headers.setdefault("User-Agent", BROWSER_USER_AGENT)
        kwargs["default_headers"] = headers
        original_init(self, *args, **kwargs)

    openai.OpenAI.__init__ = patched_init  # type: ignore[method-assign]
    openai.OpenAI._qcb_ua_patched = True  # type: ignore[attr-defined]


def build_llm(
    agent: str | None = None,
    *,
    model: str | None = None,
    provider: str | None = None,
    overrides: dict[str, str] | None = None,
    settings: dict[str, str] | None = None,
    temperature: float | None = None,
    api_key: str | None = None,
    install_user_agent: bool = True,
) -> Any:
    """Return a CrewAI ``LLM`` for ``agent``, fully configured.

    ``api_key`` may be passed explicitly (e.g. a per-tenant key from the
    database); otherwise the provider's environment variable is used.
    """
    cfg: LLMConfig = resolve(
        agent=agent,
        model=model,
        provider=provider,
        overrides=overrides,
        settings=settings,
        temperature=temperature,
    )

    key = api_key or cfg.api_key()
    if not key:
        raise MissingAPIKeyError(
            f"no API key for provider {cfg.provider!r}: set {cfg.api_key_env} "
            "in the environment or pass api_key= explicitly"
        )

    if install_user_agent and cfg.needs_browser_user_agent:
        _install_browser_user_agent()

    from crewai import LLM  # imported lazily: keeps registry import light

    return LLM(**_llm_kwargs(cfg, key))


def _llm_kwargs(cfg: LLMConfig, key: str) -> dict[str, Any]:
    """Build the kwargs handed to CrewAI's ``LLM``.

    Split out from :func:`build_llm` so the shape can be asserted in tests
    without constructing a real LLM (which would need a live provider).

    ``max_tokens`` is included ONLY when set: some providers reject an explicit
    maximum with a 400, and "uncapped" is a legitimate configuration.
    """
    kwargs: dict[str, Any] = {
        "model": cfg.crewai_model,
        "base_url": cfg.base_url,
        "api_key": key,
        "temperature": cfg.temperature,
    }
    if cfg.max_tokens:
        kwargs["max_tokens"] = cfg.max_tokens
    return kwargs


def provider_env_hint(cfg: LLMConfig) -> str:
    """Human-readable note for the admin UI about what a provider needs."""
    bits = [f"provider={cfg.provider}", f"model={cfg.model}"]
    if cfg.needs_browser_user_agent:
        bits.append("requires browser User-Agent (Cloudflare)")
    if cfg.max_prompt_tokens is not None:
        bits.append(f"max {cfg.max_prompt_tokens} prompt tokens — chunking required")
    return "; ".join(bits)


def env_template(cfg: LLMConfig) -> str:
    """Copy-pasteable .env block for the currently selected config."""
    return (
        f"LLM_PROVIDER={cfg.provider}\n"
        f"LLM_MODEL={cfg.model_alias}\n"
        f"{cfg.api_key_env}=<your-key>\n"
    )


def mask_key(value: str | None) -> str:
    """Never render a full key in logs or UI."""
    if not value:
        return "(unset)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


__all__ = [
    "MissingAPIKeyError",
    "build_llm",
    "env_template",
    "mask_key",
    "provider_env_hint",
]
