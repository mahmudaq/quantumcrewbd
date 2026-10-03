"""Agent 5 — Executive Compliance & QA Auditor.

Adversarial by construction. This agent is given the draft, the original
requirements, and the deterministic facts, and is asked to find reasons the bid
would be rejected.

Two things it must do that a normal "review this" prompt does not:

1. **Re-derive the arithmetic.** `parsing.scoring` recomputes compliance and
   total mandays. A mismatch between the writer's stated figures and the
   recomputed ones is an Accuracy finding, and the flag is set explicitly rather
   than left for the reader to notice.

2. **Distinguish "checked and fine" from "could not tell".** An unverifiable
   claim is not a pass. Findings carry `verified`, and the dossier records it,
   so the score never silently absorbs an unknown.
"""

from __future__ import annotations

from typing import Any

from agents.analyzer import _extract_json
from agents.base import NO_FABRICATION, build_agent
from models.dossiers import FinalSubmissionDossier
from parsing.scoring import Criterion, compliance_score, total_mandays
from parsing.tech6 import PART_HEADINGS, has_statutory_block

ROLE = "Executive Bid Auditor & Quality Controller"
GOAL = (
    "Red-team the draft proposal against the original tender requirements and "
    "the confirmed guidelines, across Evidence, Accuracy, Completeness, and "
    "Quality — and report every reason this bid could be rejected."
)
BACKSTORY = (
    "You are the last check before submission, and you are paid to be the "
    "pessimist. You have seen bids marked non-responsive for a missing "
    "signature block, an arithmetic error in an effort table, and a claim with "
    "no reference behind it. You never mark something verified that you could "
    "not actually check."
)

_DIMENSIONS = (
    "EVIDENCE — is every technical claim substantiated by a concrete reference?",
    "ACCURACY — hallucinations, unrealistic timelines, arithmetic that does not "
    "reconcile (recompute the effort table yourself).",
    "COMPLETENESS — 100% coverage of the mandatory criteria and the standard "
    "forms the tender actually cites.",
    "QUALITY — donor formatting rules, page limits, submission constraints.",
)

_PROMPT = """
Audit this draft proposal adversarially.

CONFIRMED FRAMEWORK: {framework}
MANDATORY FORMS (from the tender): {forms}
TECHNICAL PASS MARK: {pass_mark}

DETERMINISTIC FACTS ALREADY ESTABLISHED (do not recompute these; use them):
{deterministic}

MANDATORY CRITERIA TO CHECK THE DRAFT AGAINST:
{criteria}

DRAFT PROPOSAL:
{draft}

Audit across these four dimensions:
{dimensions}

Then:
  1. For EVERY mandatory criterion, decide pass/fail and emit ONE object into
     `criterion_assessments` with `criterion` (the criterion name), `passed`
     (true/false), `dimension`, and `evidence` (what in the draft you based the
     verdict on). If the draft does not address a criterion, `passed` is false
     with evidence "not addressed". The score is computed from these verdicts —
     do not invent a score yourself.
  2. For each defect you find, emit a `findings` entry and set its severity to
     blocker / major / minor / info. Set `verified: false` when you could NOT
     actually confirm the point from the draft: an unverifiable claim is not a pass.
  3. Check whether all 8 parts of the Form TECH-6 biodata are present
     ({tech6_parts}) and whether the statutory certification block appears.
  4. List every mandatory form the draft is missing.

{no_fabrication}

Output JSON only, matching:
{{"criterion_assessments": [{{"criterion": str, "passed": bool,
                              "dimension": str, "evidence": str}}],
  "findings": [{{"dimension": str, "severity": str, "criterion": str,
                 "finding": str, "evidence": str, "remediation": str,
                 "verified": bool}}],
  "tech6_compliant": bool, "statutory_clause_present": bool,
  "missing_forms": [str], "final_proposal_text": str}}

Set `final_proposal_text` to the draft with the detected defects corrected
in place. Keep the section structure identical.
"""


def deterministic_facts(
    phases: list[Any],
    draft_text: str,
    mandatory_forms: list[str] | None = None,
    stated_mandays: float | None = None,
) -> dict[str, Any]:
    """The arithmetic Agent 5 must reconcile against, computed in Python.

    Note what is NOT computed here: the compliance score. It cannot be — a
    compliance score counts criteria the reviewer has *assessed*, and before the
    audit runs there are no verdicts. Scoring the tender's raw requirement list
    would report 0% for a perfectly good bid, because "required" is not "failed".
    The score is derived from the reviewer's own `criterion_assessments` in
    :func:`parse_dossier`, once its verdicts exist.
    """
    recomputed = total_mandays(phases)

    forms = [f.upper() for f in (mandatory_forms or [])]
    missing = [f for f in forms if f.upper() not in (draft_text or "").upper()]

    return {
        "computed_total_mandays": recomputed,
        "stated_total_mandays": stated_mandays,
        "mandays_mismatch": (
            stated_mandays is not None
            and abs(recomputed - float(stated_mandays)) > 0.01
        ),
        "statutory_clause_present": has_statutory_block(draft_text),
        "missing_forms": missing,
    }


def build_prompt(
    draft_text: str,
    criteria: list[Any],
    framework: str = "",
    mandatory_forms: list[str] | None = None,
    pass_mark: float | None = None,
    phases: list[Any] | None = None,
    stated_mandays: float | None = None,
) -> str:
    facts = deterministic_facts(
        phases or [], draft_text, mandatory_forms, stated_mandays)

    crit_lines = []
    for c in criteria or []:
        d = c if isinstance(c, dict) else getattr(c, "model_dump", lambda: {})()
        crit_lines.append(f"  - [{'MANDATORY' if d.get('mandatory', True) else 'optional'}] "
                          f"{d.get('criterion') or d.get('name')}  "
                          f"(pass mark: {d.get('pass_mark') or 'not stated'})")

    return _PROMPT.format(
        framework=framework or "(not specified)",
        forms=", ".join(mandatory_forms or []) or "(none cited by the tender)",
        pass_mark=pass_mark if pass_mark is not None else "NOT STATED — do not assume one",
        deterministic=_fmt_facts(facts),
        criteria="\n".join(crit_lines) or "(no criteria supplied)",
        draft=(draft_text or "")[:60_000],
        dimensions="\n".join(f"  {i}. {d}" for i, d in enumerate(_DIMENSIONS, 1)),
        tech6_parts=", ".join(PART_HEADINGS),
        no_fabrication=NO_FABRICATION,
    )


def _fmt_facts(facts: dict[str, Any]) -> str:
    lines = []
    for k, v in facts.items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)


def build_reviewer(*, overrides=None, settings=None, verbose: bool = True):
    """Construct Agent 5. Needs no tools — it audits supplied text."""
    return build_agent(
        "reviewer",
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=[],
        overrides=overrides,
        settings=settings,
        verbose=verbose,
    )


def parse_dossier(
    text: str,
    *,
    phases: list[Any] | None = None,
    mandatory_forms: list[str] | None = None,
    stated_mandays: float | None = None,
    draft_text: str = "",
) -> FinalSubmissionDossier:
    """Parse the audit output, then OVERRIDE the arithmetic with ours.

    Two overrides, for the same reason — the model must not be trusted to do
    arithmetic that Python can do exactly:

    * the effort total is recomputed from the phase table, so a mis-added table
      cannot be reported as a verified figure;
    * the compliance score is recomputed from the reviewer's own
      `criterion_assessments`. The model writes verdicts; we count them.
    """
    d = FinalSubmissionDossier.model_validate(_extract_json(text))

    if d.criterion_assessments:
        score = compliance_score(d.criterion_assessments)
        d.compliance_score = round(score.score, 2)
        d.criteria_passed = score.passed
        d.criteria_total = score.total
        d.score_verdict = score.verdict
        d.score_by_dimension = score.by_dimension

    if phases is not None:
        recomputed = total_mandays(phases)
        d.recomputed_total_mandays = recomputed
        if stated_mandays is not None:
            d.mandays_mismatch = abs(recomputed - float(stated_mandays)) > 0.01

    if draft_text:
        d.statutory_clause_present = has_statutory_block(draft_text)
    if mandatory_forms:
        up = draft_text.upper()
        d.missing_forms = [f for f in mandatory_forms if f.upper() not in up]

    return d
