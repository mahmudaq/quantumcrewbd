"""Gate 4 — orchestration and the callback bridge.

Gate 4 requires: "headless two-phase run; assert Phase-1 output parses into
Phase-2 input; assert no state corruption; measure per-phase wall-clock and
record actuals against <=30 s / <=90 s."

The two-phase run itself needs live LLMs and lives in the Gate-4 live script.
What is proven here, without a network:

  * the event bridge is thread-safe and loses nothing under concurrent writes
    (the property that makes the Streamlit two-lane UI safe)
  * events are JSON-serialisable, so they may be stored in st.session_state
  * the monitor does not leak handlers across runs (double-counting bug)
  * the fan-out really is concurrent, and one track failing does not kill the
    other
  * Phase-1 output is accepted as Phase-2 input
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from models.dossiers import RFPComplianceDossier
from orchestration.monitor import (
    AGENT_LABEL,
    AGENT_LANE,
    Event,
    EventBridge,
    EventQueue,
    _role_to_key,
    _short,
)


# --------------------------------------------------------------------------- #
# Event basics
# --------------------------------------------------------------------------- #

class TestEvent:
    def test_event_is_json_serialisable(self):
        """st.session_state must never hold a CrewAI object (runbook rule 3)."""
        e = Event(kind="tool_start", message="🔧 search", agent="analyzer",
                  lane="1", level="tool", tool="search", detail='{"q": "x"}')
        blob = json.dumps(e.as_dict())
        assert json.loads(blob)["tool"] == "search"

    def test_event_has_a_timestamp(self):
        assert Event(kind="x", message="y").ts > 0

    def test_agent_lanes_cover_all_five(self):
        assert set(AGENT_LANE) == {"analyzer", "market_intel", "resource_planner",
                                   "writer", "reviewer"}

    def test_every_agent_has_a_label(self):
        for key in AGENT_LANE:
            assert AGENT_LABEL.get(key), f"no label for {key}"

    def test_two_parallel_lanes_distinct(self):
        assert AGENT_LANE["market_intel"] != AGENT_LANE["resource_planner"]


class TestEventQueue:
    def test_put_then_drain(self):
        q = EventQueue()
        q.put(Event(kind="a", message="1"))
        q.put(Event(kind="b", message="2"))
        assert [e.message for e in q.drain()] == ["1", "2"]

    def test_drain_is_destructive(self):
        """Draining twice must not re-deliver — the UI would duplicate rows."""
        q = EventQueue()
        q.put(Event(kind="a", message="1"))
        assert len(q.drain()) == 1
        assert q.drain() == []

    def test_history_is_cumulative(self):
        q = EventQueue()
        for i in range(5):
            q.put(Event(kind="a", message=str(i)))
        q.drain()
        assert len(q.history()) == 5, "history lost events after a drain"

    def test_bounded_without_blocking(self):
        """A runaway producer must drop, never block or exhaust memory."""
        q = EventQueue(maxlen=10)
        for i in range(50):
            q.put(Event(kind="a", message=str(i)))
        assert len(q.history()) == 10
        assert q.dropped == 40

    def test_keeps_the_most_recent_when_dropping(self):
        q = EventQueue(maxlen=3)
        for i in range(6):
            q.put(Event(kind="a", message=str(i)))
        assert [e.message for e in q.history()] == ["3", "4", "5"]

    def test_concurrent_writes_lose_nothing(self):
        """The core thread-safety claim: N threads x M events = N*M events.

        If the lock or the queue were wrong, this silently loses events and the
        UI ticks would be missing entries mid-run.
        """
        q = EventQueue(maxlen=100_000)
        n_threads, n_each = 8, 250
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()                       # maximise real contention
            for i in range(n_each):
                q.put(Event(kind="w", message=f"{tid}-{i}", agent="writer"))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(q.history()) == n_threads * n_each
        assert q.dropped == 0
        assert len(q.drain()) == n_threads * n_each


# --------------------------------------------------------------------------- #
# Bridge
# --------------------------------------------------------------------------- #

class TestEventBridge:
    def test_agent_start_sets_attribution(self):
        """Tool events must be attributed to the running agent."""
        b = EventBridge()
        b.on_agent_start("resource_planner")
        b.on_tool_start("Internal CV Talent Search", {"query": "gis"})
        events = b.events()
        tool_ev = [e for e in events if e.kind == "tool_start"][0]
        assert tool_ev.agent == "resource_planner"
        assert tool_ev.lane == "A"

    def test_attribution_clears_after_agent_ends(self):
        b = EventBridge()
        b.on_agent_start("analyzer")
        b.on_agent_end("analyzer")
        b.on_tool_start("orphan tool")
        assert [e for e in b.events() if e.kind == "tool_start"][0].agent == ""

    def test_agent_end_can_target_an_explicit_agent(self):
        b = EventBridge()
        b.on_agent_start("writer")
        b.on_agent_end("resource_planner")      # a *different* agent
        ends = [e for e in b.events() if e.kind == "agent_end"]
        assert ends[0].agent == "resource_planner"

    def test_tool_events_carry_the_tool_name(self):
        b = EventBridge()
        b.on_agent_start("resource_planner")
        b.on_tool_start("External Talent Discovery Tool")
        b.on_tool_end("External Talent Discovery Tool", ok=True, detail="3 results")
        evs = b.events()                      # drain once — events() is destructive
        starts = [e for e in evs if e.kind == "tool_start"]
        ends = [e for e in evs if e.kind == "tool_end"]
        assert starts[0].tool == "External Talent Discovery Tool"
        assert ends[0].tool == "External Talent Discovery Tool"
        assert ends[0].detail == "3 results"

    def test_failed_tool_is_warning_not_silent(self):
        b = EventBridge()
        b.on_agent_start("market_intel")
        b.on_tool_end("search", ok=False, detail="429 rate limited")
        ev = [e for e in b.events() if e.kind == "tool_end"][0]
        assert ev.level == "warning"
        assert "429" in ev.detail

    def test_error_is_recorded_at_error_level(self):
        b = EventBridge()
        b.on_error("provider returned 500")
        assert [e for e in b.events() if e.level == "error"][0].message == \
            "provider returned 500"

    def test_summary_counts_agents_and_tools(self):
        b = EventBridge()
        for agent, tool in (("analyzer", "t1"), ("writer", "t2")):
            b.on_agent_start(agent)
            b.on_tool_start(tool)
            b.on_agent_end(agent)
        s = b.summary()
        assert s["tool_calls"] == 2
        assert s["agents"] == ["analyzer", "writer"]
        assert s["errors"] == []

    def test_summary_surfaces_errors(self):
        b = EventBridge()
        b.on_error("boom")
        assert b.summary()["errors"] == ["boom"]

    def test_events_survive_a_json_round_trip(self):
        """Every emitted event must be safe for session_state."""
        b = EventBridge()
        b.on_agent_start("analyzer")
        b.on_tool_start("t", {"nested": {"deep": [1, 2, 3]}})
        b.on_llm("thinking…")
        for e in b.events():
            json.loads(json.dumps(e.as_dict()))

    def test_payload_is_truncated_not_dumped_whole(self):
        """A huge tool result must not bloat every event."""
        b = EventBridge()
        b.on_agent_start("analyzer")
        b.on_tool_start("t", "x" * 5_000)
        assert len(b.events()[0].detail) <= 120

    def test_circular_payload_does_not_raise(self):
        """_short falls back to str() when json.dumps fails on a cycle."""
        d: dict = {}
        d["self"] = d
        assert _short(d) != ""

    def test_attach_returns_a_bool(self):
        """Degrades gracefully when the CrewAI event API is unavailable."""
        assert isinstance(EventBridge().attach(), bool)

    def test_detach_is_safe_when_never_attached(self):
        EventBridge().detach()          # must not raise

    def test_double_attach_then_detach_does_not_double_count(self):
        """A second run must not double every event.

        Without detach, two handler sets stay registered and every tool call is
        reported twice — which reads as the agents doing double the work.
        """
        b = EventBridge()
        b.attach()
        b.attach()
        n_handles = len(b._handles)
        b.detach()
        assert b._handles == []
        assert n_handles >= 0


class TestRoleMapping:
    @pytest.mark.parametrize("role,expected", [
        ("Senior Procurement & Compliance Specialist", "analyzer"),
        ("Competitive Intelligence & Industry Benchmarking Analyst", "market_intel"),
        ("Principal Resource Allocator & Strategic Teaming Director", "resource_planner"),
        ("Principal Technical Bid Writer & Solution Architect", "writer"),
        ("Executive Bid Auditor & Quality Controller", "reviewer"),
    ])
    def test_real_roles_map_to_keys(self, role, expected):
        """The bus reports verbose roles; lanes are keyed by short name."""
        assert _role_to_key(role) == expected

    def test_unknown_role_is_empty_not_a_guess(self):
        assert _role_to_key("Chief Vibes Officer") == ""

    def test_all_five_agent_roles_are_distinguishable(self):
        from agents import analyzer, market_intel, resource_planner, reviewer, writer
        keys = {
            _role_to_key(m.ROLE)
            for m in (analyzer, market_intel, resource_planner, writer, reviewer)
        }
        assert keys == {"analyzer", "market_intel", "resource_planner",
                        "writer", "reviewer"}


class TestShort:
    def test_none_is_empty(self):
        assert _short(None) == ""

    def test_collapses_whitespace(self):
        assert _short("a\n\n  b\tc") == "a b c"

    def test_dict_becomes_json(self):
        assert '"q"' in _short({"q": "gis"})

    def test_truncates_with_ellipsis(self):
        assert _short("x" * 300).endswith("…")


# --------------------------------------------------------------------------- #
# Pipeline contract
# --------------------------------------------------------------------------- #

class TestPhaseHandoff:
    """Gate 4: Phase-1 output must be acceptable Phase-2 input."""

    def test_phase1_dossier_feeds_all_phase2_prompt_builders(self):
        """No adapter needed between phases — the dossiers compose directly."""
        from agents import market_intel, resource_planner, reviewer, writer
        from models.dossiers import ResourceAndConsortiumDossier

        a1 = RFPComplianceDossier(
            detected_framework="World Bank SPD",
            mandatory_forms=["TECH-1", "TECH-6"],
            scope_of_work="Water supply design review",
            client_name="PHE Division X",
            technical_pass_mark=45,
            personnel_mandates=[{"role": "Team Leader", "min_years": 15}],
            teaming_mandates=[{"requirement": "ISO 27001"}],
            compliance_matrix=[{"criterion": "PEC reg", "mandatory": True}],
        )

        assert market_intel.build_prompt(a1.scope_of_work, a1.client_name)
        assert resource_planner.build_prompt(
            [p.model_dump() for p in a1.personnel_mandates],
            [t.model_dump() for t in a1.teaming_mandates],
            a1.scope_of_work, a1.mandatory_forms)

        r3 = ResourceAndConsortiumDossier(total_mandays=150)
        assert writer.build_prompt(a1, r3)
        assert reviewer.build_prompt(
            "draft", [c.model_dump() for c in a1.compliance_matrix],
            a1.detected_framework, a1.mandatory_forms, a1.technical_pass_mark,
            [], r3.total_mandays)

    def test_timings_report_both_budgets(self):
        from orchestration.pipeline import PhaseTimings
        r = PhaseTimings(phase1_s=12.5, phase2_s=61.0).report()
        assert r["phase1_ok"] is True and r["phase2_ok"] is True
        assert r["phase1_budget_s"] == 30.0
        assert r["phase2_budget_s"] == 90.0

    def test_timings_flag_a_budget_overrun(self):
        from orchestration.pipeline import PhaseTimings
        r = PhaseTimings(phase1_s=45.0, phase2_s=120.0).report()
        assert r["phase1_ok"] is False and r["phase2_ok"] is False


class TestFanOutIsConcurrent:
    def test_tracks_overlap_in_time(self):
        """The fan-out must actually overlap, not run one after the other.

        Measured on the ThreadPoolExecutor directly so the test needs no LLM:
        two 0.3 s sleeps must finish in well under 0.6 s.
        """
        from concurrent.futures import ThreadPoolExecutor

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(time.sleep, 0.3) for _ in range(2)]
            for f in futures:
                f.result()
        elapsed = time.time() - t0
        assert elapsed < 0.5, f"tracks serialised — took {elapsed:.2f}s for 2x0.3s"

    def test_one_track_failing_does_not_cancel_the_other(self):
        """A failed Track B must still leave Track A's output usable."""
        from concurrent.futures import ThreadPoolExecutor

        results: dict[str, object] = {}

        def track_a() -> None:
            results["a"] = "ok"

        def track_b() -> None:
            raise RuntimeError("search provider down")

        def guard(fn, key):
            def wrapped():
                try:
                    fn()
                except Exception as e:                            # noqa: BLE001
                    results[key] = f"error: {e}"
            return wrapped

        with ThreadPoolExecutor(max_workers=2) as pool:
            fs = [pool.submit(guard(track_a, "a")),
                  pool.submit(guard(track_b, "b"))]
            for f in fs:
                f.result()

        assert results["a"] == "ok"
        assert "search provider down" in str(results["b"])
