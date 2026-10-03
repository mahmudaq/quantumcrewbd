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
    "list_models",
    "resolve",
]
