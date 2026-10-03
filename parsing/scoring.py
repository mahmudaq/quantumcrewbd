"""Compliance scoring and level-of-effort maths.

Two formulas, both specified by the MVP doc:

    Compliance Score = (Passed Mandatory Criteria / Total Mandatory Criteria) × 100
    Total Mandays    = Σ (Phase Duration in Days × FTE Allocation)

Both are pure functions here. The LLM decides *whether* a criterion is met; the
arithmetic is done in Python so a plausible-sounding narrative cannot override a
wrong number. The reviewer agent narrates; this module counts.

A note on what the score is NOT: it measures coverage of the *mandatory* gate
criteria, not the technical evaluation score. A bid can reach 100% compliance
and still lose on quality. The tender's own weighted rubric (70/70/45 in the
local corpus) is a different number and must come from the tender's evaluation
table — see `parsing.datasheet.find_evaluation_marks`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


@dataclass
class Criterion:
    """One mandatory criterion from the tender's compliance matrix."""

    name: str
    passed: bool
    dimension: str = "Completeness"      # Evidence | Accuracy | Completeness | Quality
    evidence: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Criterion:
        passed = d.get("passed")
        if passed is None:               # tolerate "status": "pass"
            status = str(d.get("status", "")).strip().lower()
            passed = status in {"pass", "passed", "yes", "true", "met", "compliant"}
        return cls(
            name=str(d.get("name") or d.get("criterion") or d.get("requirement") or ""),
            passed=bool(passed),
            dimension=str(d.get("dimension") or "Completeness"),
            evidence=str(d.get("evidence") or ""),
            note=str(d.get("note") or ""),
        )


@dataclass
class ComplianceScorecard:
    passed: int
    total: int
    score: float
    by_dimension: dict[str, dict[str, float]] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """A label a human can act on, not just a number."""
        if self.total == 0:
            return "UNSCORABLE"
        if self.score >= 95:
            return "SUBMISSION-READY"
        if self.score >= 80:
            return "CONDITIONAL — remediate listed gaps"
        return "NOT SUBMISSION-READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total": self.total,
            "score": round(self.score, 2),
            "verdict": self.verdict,
            "by_dimension": self.by_dimension,
            "failed": self.failed,
        }


def _coerce(item: Any) -> "Criterion":
    """Accept a Criterion, a plain dict, or any Pydantic model."""
    if isinstance(item, Criterion):
        return item
    if not isinstance(item, dict):
        dump = getattr(item, "model_dump", None)
        item = dump() if callable(dump) else dict(item)
    return Criterion.from_dict(item)


def compliance_score(criteria: Sequence[Any]) -> ComplianceScorecard:
    """(Passed / Total) × 100, plus a per-dimension breakdown.

    Returns a 0-scored card for an empty list rather than raising: "no mandatory
    criteria extracted" is itself a finding, and the caller needs to be able to
    show it.
    """
    items = [_coerce(c) for c in criteria]
    total = len(items)
    passed = sum(1 for c in items if c.passed)

    dims: dict[str, dict[str, float]] = {}
    for c in items:
        d = dims.setdefault(c.dimension, {"passed": 0, "total": 0})
        d["total"] += 1
        if c.passed:
            d["passed"] += 1
    for d in dims.values():
        d["score"] = round((d["passed"] / d["total"]) * 100, 2) if d["total"] else 0.0

    return ComplianceScorecard(
        passed=passed,
        total=total,
        score=(passed / total) * 100 if total else 0.0,
        by_dimension=dims,
        failed=[c.name for c in items if not c.passed],
    )


@dataclass
class Phase:
    """One project phase in the work plan."""

    name: str
    duration_days: float
    fte: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Phase:
        def _num(*keys: str) -> float:
            for k in keys:
                v = d.get(k)
                if v is None:
                    continue
                try:
                    return float(str(v).strip())
                except (TypeError, ValueError):
                    continue
            return 0.0
        return cls(
            name=str(d.get("name") or d.get("phase") or ""),
            duration_days=_num("duration_days", "days", "duration"),
            fte=_num("fte", "fte_allocation", "allocation"),
        )


def total_mandays(phases: Iterable[Phase | dict[str, Any]]) -> float:
    """Σ (Phase Duration × FTE). The reviewer re-computes this independently.

    A mismatch between the writer's stated total and this figure is exactly the
    kind of arithmetic discrepancy Agent 5's Accuracy dimension must catch.
    """
    total = 0.0
    for p in phases:
        phase = p if isinstance(p, Phase) else Phase.from_dict(p)
        total += phase.duration_days * phase.fte
    return round(total, 2)


def mandays_table(phases: Iterable[Phase | dict[str, Any]]) -> str:
    """Markdown table of the LOE breakdown, with a verified total row."""
    rows: list[str] = []
    total = 0.0
    for p in phases:
        phase = p if isinstance(p, Phase) else Phase.from_dict(p)
        md = round(phase.duration_days * phase.fte, 2)
        total += md
        rows.append(f"| {phase.name} | {phase.duration_days:g} | {phase.fte:g} | {md:g} |")
    if not rows:
        return "_No work plan provided._"
    header = ("| Phase | Duration (days) | FTE | Mandays |\n"
              "|---|---|---|---|")
    return header + "\n" + "\n".join(rows) + f"\n| **Total** | | | **{round(total, 2):g}** |"
