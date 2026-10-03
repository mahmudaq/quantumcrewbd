"""Shared agent construction.

Every agent is built the same way: resolve its LLM from the registry (never
hardcode a model), attach its tools, and hand it a prompt whose output contract
matches a Pydantic model in :mod:`models.dossiers`.

The prompts share one non-negotiable rule, stated explicitly in each: **do not
invent numbers**. A pass mark, a turnover threshold, or a mandays total that the
model "recalls" rather than reads is the failure mode that disqualifies bids.
Where a deterministic extractor exists (``parsing.datasheet``), the located text
is injected into the prompt so the model reasons over evidence rather than
searching for it.
"""

from __future__ import annotations

from typing import Any

from crewai import Agent

from llm.client import build_llm
from llm.registry import resolve

# The shared integrity clause. Deliberately blunt.
NO_FABRICATION = (
    "Never invent a number, threshold, certification, or name. If a required "
    "value is not present in the provided text, output null (or an empty list) "
    "and say so in the notes field. A fabricated pass mark or turnover figure "
    "is worse than an acknowledged gap, because it silently disqualifies the "
    "bid and cannot be spotted downstream."
)


def build_agent(
    agent_key: str,
    *,
    role: str,
    goal: str,
    backstory: str,
    tools: list[Any] | None = None,
    overrides: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
    allow_delegation: bool = False,
    verbose: bool = True,
    max_iter: int = 12,
) -> Agent:
    """Construct a CrewAI ``Agent`` with a registry-resolved LLM.

    ``agent_key`` selects the model via the registry's per-agent defaults, so
    switching the writer to a different model is a config change, not a code
    change. Called once per agent per run.
    """
    cfg = resolve(agent=agent_key, overrides=overrides, settings=settings)
    return Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=build_llm(cfg),
        tools=list(tools or []),
        allow_delegation=allow_delegation,
        verbose=verbose,
        max_iter=max_iter,
    )
