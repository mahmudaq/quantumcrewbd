"""Pipeline orchestration: two phases, with a HITL checkpoint between them.

Phase 1 — Analysis        :  Agent 1 alone. Produces the compliance dossier.
     ── HITL checkpoint ── :  the user confirms the framework and can inject CVs.
Phase 2 — Generation      :  Agents 2 and 3 run CONCURRENTLY (Tracks B and A),
                             then Agent 4, then Agent 5.

Why the checkpoint sits where it does: Agent 1's framework detection decides
which forms every downstream agent emits. If that detection is wrong, letting
Agents 2-5 run means a complete, well-formatted proposal in the wrong template —
the most expensive possible failure. So Phase 1 stops, a human confirms, and only
then does the expensive work start.

Concurrency note (R-05): CrewAI's ``Process.hierarchical`` and parallel task
execution were not usable in 1.15.23 for this shape, so the fan-out is done with
a ``ThreadPoolExecutor`` over two single-agent crews. Each track gets its own
crew and its own agent, so there is no shared mutable state between them.

Every result is plain Pydantic/JSON — no CrewAI object crosses a phase boundary,
which is what lets the UI keep runs in ``st.session_state``.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from agents import analyzer, market_intel, resource_planner, reviewer, writer
from models.dossiers import (
    DraftProposalDossier,
    FinalSubmissionDossier,
    MarketIntelligenceDossier,
    RFPComplianceDossier,
    ResourceAndConsortiumDossier,
)
from orchestration.monitor import EventBridge, EventQueue
from parsing.tech6 import Candidate, render_cv_set

# Latency budgets from the plan. Recorded against actuals, not asserted.
BUDGET_PHASE1_S = 30.0
BUDGET_PHASE2_S = 90.0


@dataclass
class PhaseTimings:
    phase1_s: float = 0.0
    phase2_s: float = 0.0
    track_a_s: float = 0.0
    track_b_s: float = 0.0

    def report(self) -> dict[str, Any]:
        return {
            "phase1_actual_s": round(self.phase1_s, 1),
            "phase1_budget_s": BUDGET_PHASE1_S,
            "phase1_ok": self.phase1_s <= BUDGET_PHASE1_S,
            "phase2_actual_s": round(self.phase2_s, 1),
            "phase2_budget_s": BUDGET_PHASE2_S,
            "phase2_ok": self.phase2_s <= BUDGET_PHASE2_S,
            "track_a_actual_s": round(self.track_a_s, 1),
            "track_b_actual_s": round(self.track_b_s, 1),
        }


@dataclass
class Phase1Result:
    dossier: RFPComplianceDossier
    raw: str
    elapsed_s: float = 0.0
    pre_extracted: dict[str, Any] = field(default_factory=dict)


@dataclass
class Phase2Result:
    market: MarketIntelligenceDossier | None = None
    resources: ResourceAndConsortiumDossier | None = None
    draft: DraftProposalDossier | None = None
    final: FinalSubmissionDossier | None = None
    rendered_cvs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _run_crew(agent, description: str, expected: str, bridge: EventBridge | None):
    """Run one single-agent crew and return the raw text output."""
    from crewai import Crew, Process, Task

    task = Task(description=description, expected_output=expected, agent=agent)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential,
                verbose=False)
    out = crew.kickoff()
    return str(out)


def run_analyzer_phase(
    raw_rfp_text: str,
    *,
    project_title: str = "",
    client_name: str = "",
    bridge: EventBridge | None = None,
    overrides: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
) -> Phase1Result:
    """Phase 1 — Agent 1 alone. Stops at the HITL checkpoint."""
    t0 = time.time()
    if bridge:
        bridge.on_agent_start("analyzer")

    prompt = analyzer.build_prompt(raw_rfp_text, project_title, client_name)
    agent = analyzer.build_analyzer(overrides=overrides, settings=settings)
    raw = _run_crew(agent, prompt, "A single JSON object matching the RFP dossier schema.",
                    bridge)
    dossier = analyzer.parse_dossier(raw)

    # Fill anything the model omitted from the deterministic extraction. The
    # parsers are exact, so their value wins over a model that guessed.
    pre = analyzer.pre_extract(raw_rfp_text)
    # The caller already knows these two — asking the model to echo them back is
    # a needless chance to get them wrong.
    if not dossier.project_title:
        dossier.project_title = project_title
    if not dossier.client_name:
        dossier.client_name = client_name
    if dossier.technical_pass_mark is None and pre["technical_pass_mark"] is not None:
        dossier.technical_pass_mark = pre["technical_pass_mark"]
    if not dossier.mandatory_forms and pre["mandatory_forms"]:
        dossier.mandatory_forms = pre["mandatory_forms"]
    if (not dossier.detected_framework or dossier.detected_framework == "Unknown") \
            and pre["detected_framework"] != "Unknown":
        dossier.detected_framework = pre["detected_framework"]
        dossier.framework_confidence = pre["framework_confidence"]
        dossier.framework_signals = pre["framework_signals"]

    if bridge:
        bridge.on_agent_end("analyzer", ok=True)

    return Phase1Result(dossier=dossier, raw=raw,
                        elapsed_s=time.time() - t0, pre_extracted=pre)


def run_proposal_generation_phase(
    analysis: RFPComplianceDossier,
    *,
    tools: list[Any] | None = None,
    injected_cvs: list[dict[str, Any]] | None = None,
    bridge: EventBridge | None = None,
    timings: PhaseTimings | None = None,
    overrides: dict[str, str] | None = None,
    settings: dict[str, Any] | None = None,
) -> Phase2Result:
    """Phase 2 — fan out Tracks B and A, then write, then review."""
    t0 = time.time()
    tm = timings or PhaseTimings()
    result = Phase2Result()

    personnel = [p.model_dump() for p in analysis.personnel_mandates]
    # User-injected CVs are appended as additional bench records — the checkpoint
    # exists precisely so a human can supply a CV the bench does not hold.
    if injected_cvs:
        personnel = personnel + [{"injected": True, **c} for c in injected_cvs]

    # ----------------------------------------------------------- Track A/B
    def track_b() -> None:
        t = time.time()
        try:
            if bridge:
                bridge.on_agent_start("market_intel")
            prompt = market_intel.build_prompt(
                analysis.scope_of_work, analysis.client_name)
            agent = market_intel.build_market_intel(
                tools or [], overrides=overrides, settings=settings)
            raw = _run_crew(agent, prompt, "A single JSON object matching the market dossier schema.",
                            bridge)
            result.market = market_intel.parse_dossier(raw)
            if bridge:
                bridge.on_agent_end("market_intel", ok=True)
        except Exception as e:                                   # noqa: BLE001
            result.errors.append(f"market_intel: {type(e).__name__}: {e}")
            if bridge:
                bridge.on_agent_end("market_intel", ok=False)
                bridge.on_error(f"market_intel failed: {e}")
        tm.track_b_s = time.time() - t

    def track_a() -> None:
        t = time.time()
        try:
            if bridge:
                bridge.on_agent_start("resource_planner")
            prompt = resource_planner.build_prompt(
                personnel, [x.model_dump() for x in analysis.teaming_mandates],
                analysis.scope_of_work, analysis.mandatory_forms)
            agent = resource_planner.build_resource_planner(
                tools or [], overrides=overrides, settings=settings)
            raw = _run_crew(agent, prompt, "A single JSON object matching the resource dossier schema.",
                            bridge)
            result.resources = resource_planner.parse_dossier(raw)
            if bridge:
                bridge.on_agent_end("resource_planner", ok=True)
        except Exception as e:                                   # noqa: BLE001
            result.errors.append(f"resource_planner: {type(e).__name__}: {e}")
            if bridge:
                bridge.on_agent_end("resource_planner", ok=False)
                bridge.on_error(f"resource_planner failed: {e}")
        tm.track_a_s = time.time() - t

    # Both tracks are independent: B needs only the analysis, A needs only the
    # analysis. Neither reads the other's output, so they run concurrently.
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(track_a), pool.submit(track_b)
        for f in (fa, fb):
            f.result()          # the track functions swallow their own errors

    # ------------------------------------------------------------- render CVs
    if result.resources and result.resources.formatted_donor_cvs:
        try:
            cands = [Candidate.from_record(c)
                     for c in result.resources.formatted_donor_cvs]
            cands = [c for c in cands if c.full_name]
            if cands:
                result.rendered_cvs = [render_cv_set(cands)]
        except Exception as e:                                   # noqa: BLE001
            result.errors.append(f"tech6 render: {type(e).__name__}: {e}")

    # ----------------------------------------------------------------- Writer
    try:
        if bridge:
            bridge.on_agent_start("writer")
        prompt = writer.build_prompt(analysis, result.resources, result.market,
                                     rendered_cvs=result.rendered_cvs)
        agent = writer.build_writer(overrides=overrides, settings=settings)
        raw = _run_crew(agent, prompt, "A single JSON object matching the draft dossier schema.",
                        bridge)
        result.draft = writer.parse_dossier(raw)
        if bridge:
            bridge.on_agent_end("writer", ok=True)
    except Exception as e:                                       # noqa: BLE001
        result.errors.append(f"writer: {type(e).__name__}: {e}")
        if bridge:
            bridge.on_agent_end("writer", ok=False)
            bridge.on_error(f"writer failed: {e}")

    # --------------------------------------------------------------- Reviewer
    if result.draft:
        try:
            if bridge:
                bridge.on_agent_start("reviewer")
            phases = ([p.model_dump() for p in result.resources.level_of_effort_table]
                      if result.resources else [])
            prompt = reviewer.build_prompt(
                result.draft.full_markdown,
                [c.model_dump() for c in analysis.compliance_matrix],
                analysis.detected_framework, analysis.mandatory_forms,
                analysis.technical_pass_mark, phases,
                result.draft.stated_total_mandays)
            agent = reviewer.build_reviewer(overrides=overrides, settings=settings)
            raw = _run_crew(agent, prompt, "A single JSON object matching the final dossier schema.",
                            bridge)
            result.final = reviewer.parse_dossier(
                raw, phases=phases, mandatory_forms=analysis.mandatory_forms,
                stated_mandays=result.draft.stated_total_mandays,
                draft_text=result.draft.full_markdown)
            if bridge:
                bridge.on_agent_end("reviewer", ok=True)
        except Exception as e:                                   # noqa: BLE001
            result.errors.append(f"reviewer: {type(e).__name__}: {e}")
            if bridge:
                bridge.on_agent_end("reviewer", ok=False)
                bridge.on_error(f"reviewer failed: {e}")
    else:
        result.errors.append("reviewer skipped: no draft produced")

    tm.phase2_s = time.time() - t0
    return result
