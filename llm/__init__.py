"""LLM provider configuration: registry, resolver, and CrewAI factory."""

from llm.registry import (
    AGENT_MODEL_DEFAULTS,
    BROWSER_USER_AGENT,
    COMMANDCODE,
    DEFAULT_MODEL_ALIAS,
    DEFAULT_PROVIDER,
    GROQ,
    KNOWN_AGENTS,
    PROVIDERS,
    LLMConfig,
    ModelSpec,
    Provider,
    list_models,
    resolve,
)

__all__ = [
    "AGENT_MODEL_DEFAULTS",
    "BROWSER_USER_AGENT",
    "COMMANDCODE",
    "DEFAULT_MODEL_ALIAS",
    "DEFAULT_PROVIDER",
    "GROQ",
    "KNOWN_AGENTS",
    "PROVIDERS",
    "LLMConfig",
    "ModelSpec",
    "Provider",
    "build_llm",
    "list_models",
    "resolve",
]


def __getattr__(name: str):
    """Lazily expose ``build_llm``.

    Importing :mod:`llm.client` pulls in CrewAI, which is heavy. The registry
    itself is imported by plain unit tests that should not need CrewAI
    installed, so the factory is resolved on first use rather than at module
    import.
    """
    if name == "build_llm":
        from llm.client import build_llm
        return build_llm
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
