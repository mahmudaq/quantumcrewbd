"""World Bank / ADB Form TECH-6 biodata formatter (FR-04).

Donors reject generic corporate or LinkedIn-style CVs; the biodata must follow
the mandated 8-part structure exactly. This module renders that structure from
canonical candidate records — no LLM, because the *format* is a compliance
artifact, not a writing task. The LLM's job is to fill the canonical fields;
rendering them into TECH-6 is deterministic so the output cannot drift.

The 8 mandated parts (MVP spec §5):
  1. Position Title and Assigned Role Number
  2. Personal Information
  3. Formal Education
  4. Professional Accreditations & Licenses
  5. Language Proficiency Matrix
  6. Chronological Employment Record
  7. Adequacy for the Assignment (assignment mapping matrix)
  8. Statutory Certification & Attestation

Part 8 is not optional — it is the legal block the donor requires, and the
reviewer (Agent 5) explicitly checks for its presence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# The statutory clause is mandated verbatim by the donor form. Keep it in one
# place so the reviewer's check and the formatter can never disagree.
STATUTORY_CERTIFICATION = (
    "I, the undersigned, certify that to the best of my knowledge and belief, "
    "this CV correctly describes my qualifications and experience. I understand "
    "that any wilful misstatement described herein may lead to my "
    "disqualification or dismissal, if engaged."
)

# Part headings, in the donor's order. Exported so the writer and reviewer can
# assert against the same list rather than each hardcoding strings.
PART_HEADINGS: tuple[str, ...] = (
    "Position Title and Assigned Role Number",
    "Personal Information",
    "Formal Education",
    "Professional Accreditations and Licenses",
    "Language Proficiency Matrix",
    "Chronological Employment Record",
    "Adequacy for the Assignment",
    "Statutory Certification and Attestation",
)

# Seniority order for the language matrix rows.
_LANGUAGE_ORDER = ("Speaking", "Reading", "Writing")


@dataclass
class Education:
    degree: str
    institution: str = ""
    year: str | int | None = None

    def render(self, index: int) -> str:
        bits = [f"{index}. {self.degree}"]
        if self.institution:
            bits.append(f"— {self.institution}")
        if self.year:
            bits.append(f"({self.year})")
        return " ".join(bits)


@dataclass
class Employment:
    period: str                       # "2015-2019" or "Mar 2015 – Jun 2019"
    employer: str
    position: str = ""
    responsibilities: str = ""

    def render(self, index: int) -> str:
        head = f"{index}. {self.period}"
        if self.employer:
            head += f" | {self.employer}"
        if self.position:
            head += f" | {self.position}"
        if self.responsibilities:
            head += f"\n   {self.responsibilities.strip()}"
        return head


@dataclass
class AdequacyMapping:
    """One row of the Part-7 assignment mapping matrix."""

    tor_task: str
    past_work: str

    def render(self, index: int) -> str:
        return (f"{index}. **Mandatory TOR Task:** {self.tor_task}\n"
                f"   **Past Work Illustrating Capability:** {self.past_work}")


@dataclass
class Candidate:
    """Canonical candidate record — the input to the TECH-6 renderer."""

    full_name: str
    position_title: str = ""
    role_number: str = ""            # e.g. "K-1"
    date_of_birth: str = ""
    nationality: str = ""
    residence: str = ""
    education: list[Education] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: dict[str, dict[str, str]] = field(default_factory=dict)
    employment: list[Employment] = field(default_factory=list)
    adequacy: list[AdequacyMapping] = field(default_factory=list)
    years_experience: int | float | None = None
    cv_summary: str = ""
    # The tender's own form list. When it does not cite TECH-6 we must not emit
    # a TECH-6 document claiming compliance with a form that was never required.
    form_code: str = "TECH-6"

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Candidate:
        """Build from a dict (a Supabase row, or an agent's JSON output).

        Tolerant by design: agent output is LLM-authored and will vary. Fields
        that arrive in the wrong shape are coerced rather than raising, because
        losing a whole candidate to a malformed `education` entry would be
        worse than rendering an empty Part 3.
        """
        def _edu(raw: Any) -> list[Education]:
            out: list[Education] = []
            if isinstance(raw, dict):
                raw = [raw]
            for item in raw if isinstance(raw, (list, tuple)) else []:
                if isinstance(item, str):
                    out.append(Education(degree=item))
                elif isinstance(item, dict):
                    out.append(Education(
                        degree=str(item.get("degree") or item.get("qualification") or ""),
                        institution=str(item.get("institution") or item.get("university") or ""),
                        year=item.get("year") or item.get("graduation_date"),
                    ))
            return out

        def _emp(raw: Any) -> list[Employment]:
            out: list[Employment] = []
            if isinstance(raw, dict):
                raw = [raw]
            for item in raw if isinstance(raw, (list, tuple)) else []:
                if isinstance(item, dict):
                    out.append(Employment(
                        period=str(item.get("period") or item.get("dates") or
                                   item.get("years") or ""),
                        employer=str(item.get("employer") or item.get("organisation") or
                                     item.get("organization") or ""),
                        position=str(item.get("position") or item.get("role") or ""),
                        responsibilities=str(item.get("responsibilities") or
                                             item.get("description") or ""),
                    ))
                elif isinstance(item, str):
                    out.append(Employment(period="", employer=item))
            return out

        def _adeq(raw: Any) -> list[AdequacyMapping]:
            out: list[AdequacyMapping] = []
            if isinstance(raw, dict):
                raw = [raw]
            for item in raw if isinstance(raw, (list, tuple)) else []:
                if isinstance(item, dict):
                    out.append(AdequacyMapping(
                        tor_task=str(item.get("tor_task") or item.get("task") or ""),
                        past_work=str(item.get("past_work") or item.get("evidence") or ""),
                    ))
            return out

        langs = record.get("languages")
        if not isinstance(langs, dict):
            langs = {}

        certs = record.get("certifications") or []
        if isinstance(certs, str):
            certs = [c.strip() for c in re.split(r"[,;]", certs) if c.strip()]

        return cls(
            full_name=str(record.get("full_name") or record.get("name") or "Unnamed Expert"),
            position_title=str(record.get("position_title") or record.get("current_role") or ""),
            role_number=str(record.get("role_number") or ""),
            date_of_birth=str(record.get("date_of_birth") or record.get("dob") or ""),
            nationality=str(record.get("nationality") or ""),
            residence=str(record.get("residence") or record.get("location") or ""),
            education=_edu(record.get("education")),
            certifications=[str(c) for c in certs],
            languages={str(k): (v if isinstance(v, dict) else {}) for k, v in langs.items()},
            employment=_emp(record.get("employment") or record.get("experience")),
            adequacy=_adeq(record.get("adequacy") or record.get("adequacy_mapping")),
            years_experience=record.get("years_experience") or record.get("experience_years"),
            cv_summary=str(record.get("cv_summary") or record.get("bio") or ""),
            form_code=str(record.get("form_code") or "TECH-6"),
        )


def _role_line(c: Candidate) -> str:
    if c.position_title and c.role_number:
        return f"{c.position_title} [{c.role_number}]"
    return c.position_title or c.role_number or "Not specified"


def render_language_matrix(languages: dict[str, dict[str, str]]) -> str:
    """Markdown table of language proficiency, donor style."""
    if not languages:
        return "_Not specified._"
    header = "| Language | Speaking | Reading | Writing |\n|---|---|---|---|"
    rows = []
    for lang, ratings in languages.items():
        cells = [str(ratings.get(k, "—")) for k in _LANGUAGE_ORDER]
        rows.append(f"| {lang} | {' | '.join(cells)} |")
    return header + "\n" + "\n".join(rows)


def missing_parts(candidate: Candidate) -> list[str]:
    """Which of the 8 mandated parts have no content.

    The reviewer uses this to distinguish "rendered but empty" from "rendered
    and populated". An empty Part 7 (adequacy mapping) is the single most common
    disqualifier, because donors score experience-to-task fit explicitly.
    """
    gaps: list[str] = []
    if not (candidate.position_title or candidate.role_number):
        gaps.append(PART_HEADINGS[0])
    if not (candidate.full_name and (candidate.nationality or candidate.date_of_birth)):
        gaps.append(PART_HEADINGS[1])
    if not candidate.education:
        gaps.append(PART_HEADINGS[2])
    if not candidate.certifications:
        gaps.append(PART_HEADINGS[3])
    if not candidate.languages:
        gaps.append(PART_HEADINGS[4])
    if not candidate.employment:
        gaps.append(PART_HEADINGS[5])
    if not candidate.adequacy:
        gaps.append(PART_HEADINGS[6])
    # Part 8 is always emitted, so it is never "missing" — but the reviewer
    # checks it separately as a presence assertion.
    return gaps


def render_tech6(candidate: Candidate, *, include_headers: bool = True) -> str:
    """Render one candidate as a complete Form TECH-6 biodata block.

    Always emits all 8 parts, using an explicit placeholder for empty ones.
    Omitting an empty part would produce a form that *looks* complete while
    silently failing the donor's structural requirement, so the gap is shown
    rather than hidden — and `missing_parts()` reports the same list
    programmatically for the Gate-3 contract test.
    """
    out: list[str] = []

    if include_headers:
        out.append(f"### Form {candidate.form_code} — Biodata of Proposed "
                   f"Professional Staff\n")

    # 1
    out.append(f"**{PART_HEADINGS[0]}**")
    out.append(_role_line(candidate))
    out.append("")

    # 2
    out.append(f"**{PART_HEADINGS[1]}**")
    out.append(f"- Name: {candidate.full_name}")
    out.append(f"- Date of Birth: {candidate.date_of_birth or 'Not specified'}")
    out.append(f"- Nationality: {candidate.nationality or 'Not specified'}")
    out.append(f"- Residence: {candidate.residence or 'Not specified'}")
    if candidate.years_experience is not None:
        out.append(f"- Total Years of Experience: {candidate.years_experience}")
    out.append("")

    # 3
    out.append(f"**{PART_HEADINGS[2]}**")
    if candidate.education:
        out.extend(e.render(i) for i, e in enumerate(candidate.education, 1))
    else:
        out.append("_Not specified._")
    out.append("")

    # 4
    out.append(f"**{PART_HEADINGS[3]}**")
    if candidate.certifications:
        out.append(", ".join(candidate.certifications))
    else:
        out.append("_None recorded._")
    out.append("")

    # 5
    out.append(f"**{PART_HEADINGS[4]}**")
    out.append(render_language_matrix(candidate.languages))
    out.append("")

    # 6
    out.append(f"**{PART_HEADINGS[5]}**")
    if candidate.employment:
        out.extend(e.render(i) for i, e in enumerate(candidate.employment, 1))
    else:
        out.append("_Not specified._")
    out.append("")

    # 7
    out.append(f"**{PART_HEADINGS[6]}**")
    if candidate.adequacy:
        out.extend(a.render(i) for i, a in enumerate(candidate.adequacy, 1))
    else:
        out.append("_No assignment mapping provided._")
    out.append("")

    # 8
    out.append(f"**{PART_HEADINGS[7]}**")
    out.append(STATUTORY_CERTIFICATION)
    out.append(f"\nSigned: ______________________  Date: "
               f"{date.today().isoformat()}")
    out.append("")

    return "\n".join(out)


def render_cv_set(candidates: list[Candidate]) -> str:
    """Render a full team's CV set for Form TECH-6 (the Annex to TECH-6)."""
    if not candidates:
        return "_No personnel proposed._\n"
    return "\n\n---\n\n".join(render_tech6(c) for c in candidates)


def has_statutory_block(text: str) -> bool:
    """True when the rendered text carries the mandated Part-8 legal block.

    Matched on a distinctive fragment rather than the whole clause so that minor
    whitespace differences do not cause a false negative.
    """
    if not text:
        return False
    return bool(re.search(
        r"certify\s+that\s+to\s+the\s+best\s+of\s+my\s+knowledge",
        text, re.IGNORECASE))
