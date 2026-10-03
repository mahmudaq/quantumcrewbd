"""Agent 4 — Lead Technical Proposal Architect.

Emits the six standard forms when the framework is World Bank / ADB, or the six
commercial sections otherwise. The form *set* comes from the analysis, not from
a hardcoded list: DOC-3 cites no TECH codes at all, and emitting a TECH-6
section for a tender that never asked for one is a formatting defect a reviewer
will catch.

The section headings are enforced verbatim — the donor's checklist is
mechanical, and a renamed section reads as a missing section.
"""

from __future__ import annotations

from typing import Any

from agents.analyzer import _extract_json
from agents.base import NO_FABRICATION, build_agent
from models.dossiers import DraftProposalDossier

ROLE = "Principal Technical Bid Writer & Solution Architect"
GOAL = (
    "Synthesise the tender analysis, market intelligence, resource plan, and "
    "formatted CVs into a persuasive technical proposal drafted strictly into "
    "the confirmed standard forms, with every claim traceable to evidence."
)
BACKSTORY = (
    "You have written winning technical proposals for multilateral consultancy "
    "contracts. You follow the donor's form structure exactly — you have seen "
    "strong bids marked down purely for reorganising the required sections. You "
    "never state a capability the resource plan does not support."
)

# The donor's form set, verbatim. Order matters: it is the submission order.
WB_ADB_FORMS: tuple[tuple[str, str], ...] = (
    ("Form TECH-1. Letter of Technical Proposal Submission", "TECH-1"),
    ("Form TECH-2. Consultant's Organisation, Experience, and Consortium Partner Profiles", "TECH-2"),
    ("Form TECH-3. Comments and Suggestions on the Terms of Reference", "TECH-3"),
    ("Form TECH-4. Description of Approach, Methodology, Work Plan, and Organisation", "TECH-4"),
    ("Form TECH-5. Work Schedule and Planning for Deliverables", "TECH-5"),
    ("Form TECH-6. Team Composition, Assignment, and Formatted Personnel CVs", "TECH-6"),
)

COMMERCIAL_SECTIONS: tuple[str, ...] = (
    "Executive Summary",
    "Technical Architecture",
    "Work Breakdown Structure and Milestones",
    "Governance and Quality Assurance",
    "Commercials",
    "Risk Management",
)


def required_headings(framework: str, mandatory_forms: list[str] | None = None) -> list[str]:
    """The exact section headings this proposal must contain.

    A multilateral framework gets the TECH-1..6 set; anything else gets the
    commercial set. When the tender names explicit forms, those are used — the
    tender's own list wins over our template.
    """
    fw = (framework or "").lower()
    forms = [f.upper() for f in (mandatory_forms or [])]

    if forms:
        headings = [h for h, code in WB_ADB_FORMS if code in forms]
        if headings:
            return headings

    if "world bank" in fw or "adb" in fw or "multilateral" in fw:
        return [h for h, _ in WB_ADB_FORMS]

    return list(COMMERCIAL_SECTIONS)


_PROMPT = """
Write the technical proposal. Draft into EXACTLY these sections, using these
headings verbatim and in this order — do not add, rename, merge, or reorder them:
{headings}

TENDER ANALYSIS:
{analysis}

{market}

RESOURCE PLAN AND CONSORTIUM:
{resources}

RENDERED FORM TECH-6 CVs (embed these verbatim, do not re-write them):
{cvs}

RULES:
  * Every technical claim must be supported by the resource plan or the market
    intelligence. If a required capability is absent from both, write the
    section around what is demonstrably available — do not assert the missing
    capability.
  * State the total level of effort as the sum of days x FTE, using the resource
    plan's figure. Do not recompute or round it.
  * Consortium roles and split percentages must match the resource plan exactly.

{no_fabrication}

Output JSON only, matching:
{{"project_title": str, "client_name": str, "framework": str,
  "sections": [{{"heading": str, "body": str}}],
  "full_markdown": str, "word_count": num,
  "stated_total_mandays": num}}

Set `full_markdown` to the complete document — all sections, in order, with a
top-level heading and each section as a Markdown `##` heading.
"""


def _fmt_obj(items: list[Any], limit: int = 30) -> str:
    if not items:
        return "(none)"
    lines = []
    for it in items[:limit]:
        d = it if isinstance(it, dict) else getattr(it, "model_dump", lambda: {})()
        lines.append("  - " + ", ".join(
            f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {})))
    return "\n".join(lines)


def build_prompt(
    analysis: Any,
    resources: Any,
    market: Any = None,
    *,
    rendered_cvs: list[str] | None = None,
) -> str:
    def _asdict(x: Any) -> dict:
        if x is None:
            return {}
        return x if isinstance(x, dict) else getattr(x, "model_dump", lambda: {})()

    a, r, m = _asdict(analysis), _asdict(resources), _asdict(market)
    framework = str(a.get("detected_framework", ""))
    headings = required_headings(framework, a.get("mandatory_forms"))

    market_block = ""
    if m:
        market_block = (
            "MARKET INTELLIGENCE:\n"
            f"  rate benchmarks: {_fmt_obj(m.get('rate_benchmarks', []), 12)}\n"
            f"  win themes: {m.get('win_themes', [])}\n"
            f"  standards: {m.get('architectural_standards', [])}"
        )

    cvs = rendered_cvs or []
    cv_block = "\n\n".join(cvs)[:24_000] if cvs else "(no CVs rendered)"

    return _PROMPT.format(
        headings="\n".join(f"  {i}. {h}" for i, h in enumerate(headings, 1)),
        analysis=f"  framework: {framework}\n"
                 f"  pass mark: {a.get('technical_pass_mark')}\n"
                 f"  forms: {a.get('mandatory_forms')}\n"
                 f"  scope: {str(a.get('scope_of_work', ''))[:2000]}\n"
                 f"  compliance matrix: {_fmt_obj(a.get('compliance_matrix', []), 20)}",
        market=market_block,
        resources=f"  personnel: {_fmt_obj(r.get('key_personnel_table', []), 20)}\n"
                  f"  consortium: {_fmt_obj(r.get('consortium_structure', []), 15)}\n"
                  f"  LOE: {_fmt_obj(r.get('level_of_effort_table', []), 20)}\n"
                  f"  total mandays: {r.get('total_mandays')}\n"
                  f"  unfilled roles: {r.get('unfilled_roles', [])}",
        cvs=cv_block,
        no_fabrication=NO_FABRICATION,
    )


def build_writer(*, overrides=None, settings=None, verbose: bool = True):
    """Construct Agent 4. Needs no tools — it works from upstream output."""
    return build_agent(
        "writer",
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=[],
        overrides=overrides,
        settings=settings,
        verbose=verbose,
    )


def parse_dossier(text: str) -> DraftProposalDossier:
    d = DraftProposalDossier.model_validate(_extract_json(text))
    # Keep full_markdown consistent with the structured sections when a model
    # fills only one of them. Downstream (reviewer, download) uses full_markdown.
    if not d.full_markdown and d.sections:
        d.full_markdown = "\n\n".join(
            f"## {s.heading}\n\n{s.body}" for s in d.sections)
    return d
