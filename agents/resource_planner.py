"""Agent 3 — Resource & Consortium Planner (TECH-6 Engine).

Runs in Track A, in parallel with Agent 2. This is the agent that makes the
flagship feature work: it queries the internal bench, falls back to web
discovery on gaps, and renders each selected candidate into Form TECH-6.

The TECH-6 rendering itself is deterministic (:mod:`parsing.tech6`). The agent
supplies canonical candidate data; the formatter guarantees structure. That
split is deliberate — the donor's format is a compliance artifact, not a
creative-writing task, and a model re-formatting it each run would drift.

Two behaviours that come straight from the tools' design:
  * The internal CV search returns "[INTERNAL BENCH VACANCY: ...]" when it finds
    nobody. That string is the trigger to go external — the agent must not
    invent an internal candidate to fill a gap.
  * `unfilled_roles` is a legitimate outcome. A roster with a hole is a decision
    the user can act on at the HITL checkpoint; a roster padded with a
    fabricated CV is a disqualification.
"""

from __future__ import annotations

from typing import Any

from agents.analyzer import _extract_json
from agents.base import NO_FABRICATION, build_agent
from models.dossiers import ResourceAndConsortiumDossier

ROLE = "Principal Resource Allocator & Strategic Teaming Director"
GOAL = (
    "Build a verified key-personnel roster and consortium teaming structure that "
    "satisfies every mandated role, certification, and turnover threshold — "
    "using internal bench first, external discovery only where the internal "
    "bench has a genuine gap — and format each proposed expert's CV into the "
    "donor's Form TECH-6 biodata structure."
)
BACKSTORY = (
    "You assemble bid teams against hard eligibility gates. You know that "
    "placing a candidate who does not hold a mandated certification is worse "
    "than leaving the role open, because the whole proposal is rejected. You "
    "always state the level of effort as days x FTE and never round a total to "
    "make it look cleaner."
)

_PROMPT = """
Build the resource and consortium plan for this bid.

MANDATED PERSONNEL (from the tender analysis):
{personnel}

MANDATED TEAMING REQUIREMENTS (certifications, turnover, JV rules):
{teaming}

SCOPE OF WORK:
{scope}

MANDATORY FORMS: {forms}

WORKING METHOD:
  1. For each mandated role, call `Internal CV Talent Search` with the role, its
     minimum years, and its mandatory certifications.
  2. If the tool returns "[INTERNAL BENCH VACANCY: ...]", that role is a real
     gap. Call `External Talent Discovery Tool` to find a benchmark, and record
     `source: "external"` plus a note that the candidate is unvetted. If no
     mandate is met, list the role in `unfilled_roles` — do NOT propose someone
     who fails a hard requirement.
  3. For each mandated corporate requirement (ISO 27001, CMMI, turnover),
     call `Internal Consortium Partner Search`, falling back to
     `External Partner Discovery Tool` on a gap.
  4. Assign level of effort per project phase as `duration_days` and `fte`.
     Compute `total_mandays` as the sum of days x FTE and state the arithmetic.

{no_fabrication}

Never re-format a CV yourself: report the candidate's canonical fields in
`formatted_donor_cvs` as a list of objects, one per candidate, with the keys
`full_name`, `position_title`, `role_number`, `education` (a list of objects
with `degree`, `institution`, `year`), `certifications` (list of strings),
`languages` (object of language -> object with `Speaking`/`Reading`/`Writing`),
`employment` (list of objects with `period`, `employer`, `position`,
`responsibilities`), `adequacy` (list of objects with `tor_task` and
`past_work`), and `years_experience`. A deterministic renderer turns those into
Form TECH-6 afterwards.

For `adequacy`, map each relevant TOR task to past work that demonstrates it.
An empty adequacy mapping is the most common reason a donor scores an expert
zero, so populate it wherever the bench record supports it.

Output JSON only, matching:
{{"key_personnel_table": [{{"role": str, "candidate_name": str,
                            "source": "internal"|"external"|"unfilled",
                            "years_experience": num, "meets_mandate": bool,
                            "gap_notes": str}}],
  "consortium_structure": [{{"partner_name": str, "domain": str,
                             "certifications": [str], "role_in_consortium": str,
                             "split_percent": num, "source": str}}],
  "level_of_effort_table": [{{"phase": str, "duration_days": num, "fte": num}}],
  "total_mandays": num, "unfilled_roles": [str], "bench_vacancies": [str],
  "formatted_donor_cvs": [object], "cv_gaps": [str], "sourcing_notes": str}}
"""


def build_prompt(
    personnel_mandates: list[Any],
    teaming_mandates: list[Any],
    scope_of_work: str = "",
    mandatory_forms: list[str] | None = None,
) -> str:
    def _fmt(items: list[Any]) -> str:
        if not items:
            return "(none specified)"
        lines = []
        for it in items:
            d = it if isinstance(it, dict) else getattr(it, "model_dump", lambda: {})()
            lines.append("  - " + ", ".join(
                f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {})))
        return "\n".join(lines)

    return _PROMPT.format(
        personnel=_fmt(personnel_mandates),
        teaming=_fmt(teaming_mandates),
        scope=scope_of_work or "(not supplied)",
        forms=", ".join(mandatory_forms or []) or "(infer from the framework)",
        no_fabrication=NO_FABRICATION,
    )


def build_resource_planner(tools: list[Any], *, overrides=None, settings=None,
                           verbose: bool = True):
    """Construct Agent 3. Needs the four sourcing tools."""
    return build_agent(
        "resource_planner",
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=tools,
        overrides=overrides,
        settings=settings,
        verbose=verbose,
        max_iter=20,          # more tool calls than the other agents
    )


def parse_dossier(text: str) -> ResourceAndConsortiumDossier:
    return ResourceAndConsortiumDossier.model_validate(_extract_json(text))
