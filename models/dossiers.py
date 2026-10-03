"""Pydantic output models for the five agent dossiers.

These are the contracts between agents. CrewAI passes text between tasks, so
without a declared schema a model can silently rename `personnel_mandates` to
`required_staff` and the next agent simply finds nothing — a failure that looks
like "the LLM had a bad day" rather than a broken interface.

Definitions are deliberately tolerant (extra fields allowed, sensible defaults)
because the LLM fills them and pedantic rejection loses an entire run. What is
NOT tolerant is the *key set*: `handoff_keys()` and the Gate-3 contract test
assert that what Agent N emits is what Agent N+1 reads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #

_FRAMEWORKS = Literal[
    "World Bank SPD", "ADB QCBS", "PPRA SBD", "Multilateral SPD (donor unspecified)",
    "Multilateral SPD (partial)", "Custom Commercial", "Unknown",
]


class _Base(BaseModel):
    """Lenient base — extra keys are kept, not rejected."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Agent 1 — RFP Compliance
# --------------------------------------------------------------------------- #

class PersonnelMandate(_Base):
    role: str = ""
    role_code: str = ""                      # "K-1", "Key Expert 1"
    min_years: float | None = None
    min_degree: str = ""
    required_certifications: list[str] = Field(default_factory=list)
    notes: str = ""


class TeamingMandate(_Base):
    requirement: str = ""
    kind: str = ""                           # ISO / CMMI / turnover / JV-liability
    mandatory: bool = True


class ComplianceItem(_Base):
    """One row of the mandatory compliance matrix.

    `pass_mark` is per-item and must come from the tender. Never default a
    threshold — DOC-3's gate is 45, DOC-1/2's is 70, and hardcoding either
    disqualifies the bid on the other.
    """

    criterion: str = ""
    mandatory: bool = True
    pass_mark: float | None = None
    evidence_required: str = ""
    source: str = ""                         # where in the tender it was found


class RFPComplianceDossier(_Base):
    """Agent 1 output. Triggers the HITL checkpoint."""

    project_title: str = ""
    client_name: str = ""
    detected_framework: str = "Unknown"
    framework_confidence: Literal["high", "medium", "low"] = "low"
    framework_signals: list[str] = Field(default_factory=list)

    selection_method: str = ""               # QCBS / QBS / ...
    envelope_scheme: str = ""                # One-Envelope / Two-Envelope
    technical_pass_mark: float | None = None
    technical_total_marks: float | None = None

    mandatory_forms: list[str] = Field(default_factory=list)
    compliance_matrix: list[ComplianceItem] = Field(default_factory=list)
    personnel_mandates: list[PersonnelMandate] = Field(default_factory=list)
    teaming_mandates: list[TeamingMandate] = Field(default_factory=list)
    scope_of_work: str = ""
    deliverables: list[str] = Field(default_factory=list)
    evaluation_weights: dict[str, float] = Field(default_factory=dict)
    extraction_notes: str = ""

    @field_validator("technical_pass_mark", "technical_total_marks", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        """LLMs emit "" / "N/A" / "not specified" for absent numbers."""
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if not s or s.lower() in {"n/a", "na", "none", "not specified", "unknown", "-"}:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return v

    def mandatory_count(self) -> int:
        return sum(1 for c in self.compliance_matrix if c.mandatory)


# --------------------------------------------------------------------------- #
# Agent 2 — Market Intelligence
# --------------------------------------------------------------------------- #

class RateBenchmark(_Base):
    role: str = ""
    jurisdiction: str = ""
    currency: str = ""
    low: float | None = None
    high: float | None = None
    unit: str = "per day"
    source: str = ""


class MarketIntelligenceDossier(_Base):
    """Agent 2 output."""

    target_jurisdiction: str = ""
    technology_domain: str = ""
    rate_benchmarks: list[RateBenchmark] = Field(default_factory=list)
    architectural_standards: list[str] = Field(default_factory=list)
    case_references: list[str] = Field(default_factory=list)
    competitor_angles: list[str] = Field(default_factory=list)
    win_themes: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: str = ""


# --------------------------------------------------------------------------- #
# Agent 3 — Resource & Consortium
# --------------------------------------------------------------------------- #

class KeyPersonnelEntry(_Base):
    role: str = ""
    role_code: str = ""
    candidate_name: str = ""
    source: Literal["internal", "external", "unfilled", ""] = ""
    years_experience: float | None = None
    certifications: list[str] = Field(default_factory=list)
    meets_mandate: bool = False
    gap_notes: str = ""


class ConsortiumMember(_Base):
    partner_name: str = ""
    domain: str = ""
    certifications: list[str] = Field(default_factory=list)
    turnover: str = ""
    role_in_consortium: str = ""             # Prime / Associate / Sub
    split_percent: float | None = None
    source: Literal["internal", "external", ""] = ""


class LevelOfEffortEntry(_Base):
    phase: str = ""
    duration_days: float = 0
    fte: float = 0


class ResourceAndConsortiumDossier(_Base):
    """Agent 3 output. Carries the TECH-6-rendered CVs."""

    key_personnel_table: list[KeyPersonnelEntry] = Field(default_factory=list)
    consortium_structure: list[ConsortiumMember] = Field(default_factory=list)
    level_of_effort_table: list[LevelOfEffortEntry] = Field(default_factory=list)
    total_mandays: float | None = None
    unfilled_roles: list[str] = Field(default_factory=list)
    bench_vacancies: list[str] = Field(default_factory=list)
    # Rendered Markdown per candidate — the writer embeds these verbatim.
    formatted_donor_cvs: list[dict[str, str]] = Field(default_factory=list)
    cv_gaps: list[str] = Field(default_factory=list)
    sourcing_notes: str = ""


# --------------------------------------------------------------------------- #
# Agent 4 — Writer
# --------------------------------------------------------------------------- #

class ProposalSection(_Base):
    heading: str = ""
    body: str = ""


class DraftProposalDossier(_Base):
    """Agent 4 output. Ordered sections, rendered to submission Markdown."""

    project_title: str = ""
    client_name: str = ""
    framework: str = ""
    sections: list[ProposalSection] = Field(default_factory=list)
    full_markdown: str = ""
    word_count: int | None = None
    stated_total_mandays: float | None = None   # Agent 5 re-computes and compares

    def section_headings(self) -> list[str]:
        return [s.heading for s in self.sections]


# --------------------------------------------------------------------------- #
# Agent 5 — Reviewer
# --------------------------------------------------------------------------- #

class AuditFinding(_Base):
    dimension: Literal["Evidence", "Accuracy", "Completeness", "Quality", "Other"] = "Other"
    severity: Literal["blocker", "major", "minor", "info"] = "minor"
    criterion: str = ""
    finding: str = ""
    evidence: str = ""
    remediation: str = ""
    # Distinguishes "the model found a real defect" from "the model could not
    # tell" — the second is not a pass and must never be silently upgraded.
    verified: bool = True


class FinalSubmissionDossier(_Base):
    """Agent 5 output. The persisted artifact."""

    compliance_score: float = 0.0
    criteria_passed: int = 0
    criteria_total: int = 0
    score_verdict: str = ""
    score_by_dimension: dict[str, dict[str, float]] = Field(default_factory=dict)

    # The reviewer's per-criterion verdicts. The score is computed from THESE in
    # Python, not from the model's arithmetic — see agents/reviewer.py. Without
    # this list there is no verdict to count, and a score computed from the
    # unassessed requirements would always be 0%.
    criterion_assessments: list[ComplianceItem] = Field(default_factory=list)

    # Arithmetic the reviewer re-derived, so a mismatch is visible.
    recomputed_total_mandays: float | None = None
    mandays_mismatch: bool = False           # stated vs recomputed LOE total
    score_mismatch: bool = False

    findings: list[AuditFinding] = Field(default_factory=list)
    tech6_compliant: bool = False
    statutory_clause_present: bool = False
    missing_forms: list[str] = Field(default_factory=list)
    final_proposal_text: str = ""

    def blockers(self) -> list[AuditFinding]:
        return [f for f in self.findings if f.severity == "blocker"]


# --------------------------------------------------------------------------- #
# Registry — used by the Gate-3 contract tests and the orchestrator
# --------------------------------------------------------------------------- #

AGENT_OUTPUT_MODELS: dict[str, type[_Base]] = {
    "analyzer": RFPComplianceDossier,
    "market_intel": MarketIntelligenceDossier,
    "resource_planner": ResourceAndConsortiumDossier,
    "writer": DraftProposalDossier,
    "reviewer": FinalSubmissionDossier,
}

# Which keys each downstream agent reads, by upstream producer. The Gate-3
# contract test asserts every key here exists on the producing model — catching
# an interface drift at test time instead of mid-run.
HANDOFF_CONTRACTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("analyzer", "market_intel"): (
        "scope_of_work", "client_name", "project_title", "compliance_matrix",
    ),
    ("analyzer", "resource_planner"): (
        "personnel_mandates", "teaming_mandates", "compliance_matrix",
        "mandatory_forms",
    ),
    ("analyzer", "writer"): (
        "detected_framework", "mandatory_forms", "technical_pass_mark",
        "selection_method", "envelope_scheme", "compliance_matrix",
    ),
    ("market_intel", "writer"): (
        "rate_benchmarks", "win_themes", "architectural_standards",
    ),
    ("resource_planner", "writer"): (
        "key_personnel_table", "consortium_structure", "level_of_effort_table",
        "formatted_donor_cvs", "total_mandays",
    ),
    ("writer", "reviewer"): (
        "full_markdown", "sections", "stated_total_mandays",
    ),
    ("analyzer", "reviewer"): (
        "compliance_matrix", "mandatory_forms", "technical_pass_mark",
    ),
}


def model_for(agent: str) -> type[_Base]:
    """Look up an agent's declared output model. Raises on unknown agent."""
    try:
        return AGENT_OUTPUT_MODELS[agent]
    except KeyError:
        raise KeyError(
            f"No output model declared for agent {agent!r}. "
            f"Known: {sorted(AGENT_OUTPUT_MODELS)}"
        ) from None
