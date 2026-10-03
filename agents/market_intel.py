"""Agent 2 — Market & Competitor Intelligence Analyst.

Runs in Track B, in parallel with Agent 3. Its job is external grounding:
day-rates, technical standards, and win themes. Every rate must carry a source,
because an ungrounded number in a commercial section is a liability.
"""

from __future__ import annotations

from typing import Any

from agents.base import NO_FABRICATION, build_agent
from agents.analyzer import _extract_json
from models.dossiers import MarketIntelligenceDossier

ROLE = "Competitive Intelligence & Industry Benchmarking Analyst"
GOAL = (
    "Ground the bid's commercial and technical sections in external evidence: "
    "benchmark day-rates for the required roles in the target jurisdiction, the "
    "prevailing technical and open standards, and the differentiators that win "
    "this class of assignment."
)
BACKSTORY = (
    "You benchmark consultancy rates across South Asian and multilateral "
    "markets. You never quote a rate without its source, and you distinguish "
    "clearly between what you found and what you estimate — clients act on your "
    "numbers when pricing a bid."
)

_PROMPT = """
Analyze this assignment and produce market intelligence.

SCOPE OF WORK:
{scope}

CLIENT / JURISDICTION: {client_name} — {jurisdiction}
TECHNOLOGY DOMAIN: {domain}
ROLES REQUIRED: {roles}

Use your search tools for:
  1. Prevailing day-rates for each required role in the target jurisdiction.
     Use local currency and state the unit. Record the source URL for each.
  2. Relevant technical standards, open standards, or digital public
     infrastructure guidelines that the proposal should cite.
  3. Comparable assignments delivered in the region (case references).
  4. Differentiators that win this class of tender.

{no_fabrication}

If a search returns nothing useful for a role, omit that role's benchmark
entirely rather than estimating. An absent benchmark is honest; an invented one
is a commercial liability.

Output JSON only, matching:
{{"target_jurisdiction": str, "technology_domain": str,
  "rate_benchmarks": [{{"role": str, "jurisdiction": str, "currency": str,
                        "low": num, "high": num, "unit": str, "source": str}}],
  "architectural_standards": [str], "case_references": [str],
  "competitor_angles": [str], "win_themes": [str], "sources": [str],
  "notes": str}}
"""


def build_prompt(
    scope_of_work: str,
    client_name: str = "",
    jurisdiction: str = "",
    domain: str = "",
    roles: list[str] | None = None,
) -> str:
    return _PROMPT.format(
        scope=scope_of_work or "(not supplied)",
        client_name=client_name or "(not supplied)",
        jurisdiction=jurisdiction or "(infer from the client)",
        domain=domain or "(infer from the scope)",
        roles=", ".join(roles or []) or "(infer from the scope)",
        no_fabrication=NO_FABRICATION,
    )


def build_market_intel(tools: list[Any], *, overrides=None, settings=None,
                       verbose: bool = True):
    """Construct Agent 2. Needs at least one search tool."""
    return build_agent(
        "market_intel",
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=tools,
        overrides=overrides,
        settings=settings,
        verbose=verbose,
    )


def parse_dossier(text: str) -> MarketIntelligenceDossier:
    return MarketIntelligenceDossier.model_validate(_extract_json(text))
