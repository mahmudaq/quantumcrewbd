"""Agent 1 — RFP & Compliance Deconstruction Specialist.

The critical design decision: this agent does **not** search the tender for
numbers. `parsing.datasheet` locates the Data Sheet and the pass mark
deterministically, and that evidence is injected into the prompt. The LLM's job
is to *interpret and structure* what the extractors found, plus read the
qualitative requirements (who is mandated, what certifications, what teaming).

That split exists because the naive design — hand the model 23k tokens and ask
for the pass mark — got it wrong on 2 of 4 real tenders, including reporting 70
where the truth was 45.
"""

from __future__ import annotations

import json
from typing import Any

from agents.base import NO_FABRICATION, build_agent
from models.dossiers import RFPComplianceDossier
from parsing import datasheet as ds

ROLE = "Senior Procurement & Compliance Specialist"
GOAL = (
    "Analyze a raw tender document and extract the mandatory pass/fail criteria, "
    "required standard forms, key personnel mandates, consortium prerequisites, "
    "and the governing procurement framework — precisely, citing where each "
    "requirement was found."
)
BACKSTORY = (
    "You have spent 20 years preparing bids for public-sector consultancies "
    "under World Bank, ADB, and national procurement rules. You have seen firms "
    "disqualified for a missing ISO certificate, a pass mark read from the wrong "
    "table, and a form set taken from the wrong donor template. You trust the "
    "document over your memory, and you would rather report 'not stated' than "
    "guess a threshold."
)

_INSTRUCTIONS = """
You are given a tender document. Work in this order.

STEP 1 — Use the PRE-EXTRACTED FACTS below as authoritative. These were derived
from the document by deterministic parsers, not by inference:
{extracted}
Do not contradict them. If you believe one is wrong, say so in `extraction_notes`
and explain why — but keep the extracted value in the structured field.

STEP 2 — From the document text, extract the QUALITATIVE requirements the
parsers cannot see:
  * Every mandatory pass/fail criterion (margin of preference rules, turnover
    minimums, bid security, registration requirements, affidavits, experience
    thresholds). For each, record `criterion`, `mandatory`, `evidence_required`,
    and `source` (the clause or paragraph you took it from).
  * Every key personnel role mandated, with its minimum years of experience,
    minimum degree, and any mandatory certifications.
  * Every consortium / teaming mandate (ISO 27001, CMMI, JV liability, minimum
    associate share).
  * The scope of work and the deliverables list.

STEP 3 — Fill `evaluation_weights` ONLY if the document states explicit
per-criterion marks. Do not derive them.

{no_fabrication}

Output a single JSON object matching this schema. Output JSON only, no prose
around it:
{schema}
"""


EXTRACTED_KEYS = (
    "detected_framework", "framework_confidence", "framework_signals",
    "selection_method", "envelope_scheme", "technical_pass_mark",
    "technical_total_marks", "mandatory_forms", "evaluation_marks",
)


def pre_extract(raw_rfp_text: str) -> dict[str, Any]:
    """Run the deterministic parsers. This is the grounding the LLM receives."""
    sheet = ds.locate_data_sheet(raw_rfp_text)
    pass_mark = ds.find_pass_mark(raw_rfp_text, data_sheet=sheet)
    framework = ds.detect_framework(raw_rfp_text)

    out: dict[str, Any] = {
        "data_sheet_found": bool(sheet),
        "data_sheet_offset": sheet.start if sheet else None,
        "detected_framework": framework["framework"],
        "framework_confidence": framework["confidence"],
        "framework_signals": framework["signals"],
        "selection_method": ds.find_selection_method(raw_rfp_text) or "",
        "envelope_scheme": ds.find_envelope_scheme(raw_rfp_text) or "",
        "technical_pass_mark": pass_mark.mark if pass_mark else None,
        "pass_mark_evidence": pass_mark.evidence if pass_mark else None,
        "pass_mark_strategy": pass_mark.strategy if pass_mark else None,
        "mandatory_forms": ds.find_required_forms(raw_rfp_text),
        "evaluation_marks": ds.find_evaluation_marks(raw_rfp_text),
    }
    if sheet:
        out["data_sheet_excerpt"] = sheet.text[:6_000]
    return out


def build_prompt(
    raw_rfp_text: str,
    project_title: str = "",
    client_name: str = "",
    *,
    max_tender_chars: int = 60_000,
) -> str:
    """Assemble the analyzer prompt with the extracted facts inline."""
    facts = pre_extract(raw_rfp_text)
    tender = raw_rfp_text[:max_tender_chars]

    schema = json.dumps(RFPComplianceDossier.model_json_schema(), indent=2)[:8_000]

    instructions = _INSTRUCTIONS.format(
        extracted=json.dumps(facts, indent=2)[:4_000],
        no_fabrication=NO_FABRICATION,
        schema=schema,
    )

    return (
        f"PROJECT TITLE: {project_title or '(not supplied)'}\n"
        f"CLIENT: {client_name or '(not supplied)'}\n\n"
        f"{instructions}\n\n"
        f"=== TENDER DOCUMENT TEXT ===\n{tender}"
    )


def build_analyzer(
    tools: list[Any] | None = None,
    *,
    overrides: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
    verbose: bool = True,
):
    """Construct Agent 1."""
    return build_agent(
        "analyzer",
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=tools,
        overrides=overrides,
        settings=settings,
        verbose=verbose,
    )


def parse_dossier(text: str) -> RFPComplianceDossier:
    """Parse the agent's JSON output into the declared model.

    Tolerates a fenced ```json block, or prose around a JSON object, because
    models wrap output despite being told not to.
    """
    return RFPComplianceDossier.model_validate(_extract_json(text))


def _extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model's output, tolerantly.

    Models wrap their JSON in prose or a fenced block, and — critically — they
    emit *unescaped control characters* when a string value contains markdown.
    A proposal body is full of newlines, so the writer regularly produces:

        {"body": "## Section

        Some text"}

    which is invalid JSON. Standard ``json.loads`` rejects it with
    "Expecting ',' delimiter" or "Invalid control character". This was
    intermittent in practice: the same prompt parsed on two runs and failed on
    the third, so it read as flakiness rather than a bug.

    ``strict=False`` is the documented stdlib escape hatch that permits literal
    control characters inside strings, and it fixes this class of failure
    without weakening anything else.

    All five agents share this function, so the hardening applies to every
    dossier, not just the writer's.
    """
    import re

    if not text or not text.strip():
        raise ValueError("agent returned empty output")

    candidates: list[str] = []

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    elif start != -1:
        # Opening brace but no closing one at all — the model was cut off
        # mid-object. Hand the raw remainder to the repair pass rather than
        # discarding the run.
        candidates.append(text[start:])

    if not candidates:
        raise ValueError(f"no JSON object found in agent output: {text[:200]!r}")

    errors: list[str] = []
    for blob in candidates:
        # Fast path: the model escaped everything correctly.
        try:
            return json.loads(blob)
        except json.JSONDecodeError as exc:
            errors.append(f"strict: {exc}")

        # Real path: literal newlines/tabs inside string values.
        try:
            return json.loads(blob, strict=False)
        except json.JSONDecodeError as exc:
            errors.append(f"non-strict: {exc}")

        # Last resort: a truncated blob. Models hit the output cap mid-object
        # or mid-string; salvaging is better than losing the run, because every
        # dossier field is optional with a sane default and the reviewer checks
        # completeness downstream.
        #
        # Order matters — most specific truncation first:
        #   '"}  ..cut inside a string value, object still open
        #   ']}  ..cut inside a string, inside an array in an object
        #   }    ..value complete, object close missing
        #   ]}   ..array + object close missing
        for suffix in ('"}', '"]}', '"}]}', '}', ']}', '}]}', '"'):
            try:
                return json.loads(blob + suffix, strict=False)
            except json.JSONDecodeError:
                continue

    raise ValueError(
        "could not parse agent JSON after strict, non-strict and repair "
        f"attempts: {'; '.join(errors)}"
    )
