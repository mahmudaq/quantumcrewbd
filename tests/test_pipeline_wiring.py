"""Wiring tests for the pipeline's agent calls.

These exist because of a real regression: commit c24622a added a `label=` keyword
to `_run_crew` and, in the same find-and-replace, dropped the `bridge` argument
from all five call sites -- while `bridge` stayed a required positional
parameter. Every agent call raised TypeError. The whole unit suite passed anyway,
because no test ever called a `run_*_phase` function: they exercised the parsers
and the retry helper directly, never the wiring between them.

So these tests deliberately stub the pieces around the seam and assert on what
the pipeline actually hands `_run_crew`. The parser tests could not catch this.
"""

from __future__ import annotations

import inspect
import re

import pytest

from orchestration import pipeline, resilience
from orchestration.pipeline import _run_crew, run_analyzer_phase
from orchestration.resilience import is_transient


# --- the calling convention -------------------------------------------------

def test_bridge_is_still_a_required_parameter():
    """A default on `bridge` would let a call site drop it silently again."""
    sig = inspect.signature(_run_crew)
    assert "bridge" in sig.parameters, "bridge must remain an explicit parameter"
    assert sig.parameters["bridge"].default is inspect.Parameter.empty, (
        "bridge must stay required -- c24622a shipped with a call site that "
        "omitted it, and the default would have hidden that"
    )


def test_every_call_site_forwards_bridge():
    """Pin the exact seam that broke: bridge must precede label= at every call."""
    src = inspect.getsource(pipeline)
    calls = [
        c for c in re.findall(r"_run_crew\((.*?)\)\n", src)
        if "prompt" in c
    ]
    assert len(calls) == 5, f"expected 5 agent call sites, found {len(calls)}"
    for call in calls:
        head = call.split("label=")[0]
        assert "bridge" in head, (
            f"call site omits the bridge argument: _run_crew({call})"
        )


# --- dynamic: the bridge actually reaches _run_crew -------------------------

class _RecordingBridge:
    """Minimal stand-in recording the events the pipeline emits."""

    def __init__(self):
        self.started: list[str] = []
        self.ended: list[str] = []
        self.errors: list[str] = []

    def on_agent_start(self, agent: str) -> None:
        self.started.append(agent)

    def on_agent_end(self, agent: str, ok: bool = True) -> None:
        self.ended.append(agent)

    def on_error(self, message: str) -> None:
        self.errors.append(message)


_VALID_DOSSIER = (
    '{"project_title": "T", "client_name": "C", "technical_pass_mark": 75}'
)


def _stub_analyzer(monkeypatch):
    """Keep the test off the network: the real build_analyzer needs an API key."""
    monkeypatch.setattr(pipeline.analyzer, "build_analyzer",
                        lambda overrides=None, settings=None: object())


def test_run_analyzer_phase_passes_the_bridge_to_run_crew(monkeypatch):
    """The exact regression: `bridge` must reach _run_crew, not be dropped."""
    _stub_analyzer(monkeypatch)
    seen: dict[str, object] = {}

    def fake_run_crew(agent, description, expected, bridge, *, label="agent"):
        seen["bridge"] = bridge
        seen["label"] = label
        return _VALID_DOSSIER

    monkeypatch.setattr(pipeline, "_run_crew", fake_run_crew)

    bridge = _RecordingBridge()
    result = run_analyzer_phase(
        "Request for Proposals. Minimum technical score: 75 points.",
        project_title="T", client_name="C", bridge=bridge,
    )

    assert isinstance(result, pipeline.Phase1Result)
    assert seen["bridge"] is bridge, "bridge was not forwarded to _run_crew"
    assert seen["label"] == "analyzer"
    assert bridge.started == ["analyzer"]


def test_run_analyzer_phase_works_without_a_bridge(monkeypatch):
    """A headless run (no UI) must not require a bridge object."""
    _stub_analyzer(monkeypatch)

    def fake_run_crew(agent, description, expected, bridge, *, label="agent"):
        assert bridge is None
        return _VALID_DOSSIER

    monkeypatch.setattr(pipeline, "_run_crew", fake_run_crew)
    result = run_analyzer_phase("Min technical score: 75 points.",
                                project_title="T", client_name="C")
    assert result.dossier is not None


# --- the empty-response guard from the same commit --------------------------

def test_empty_kickoff_is_raised_not_returned(monkeypatch):
    """An empty completion must raise so the retry path sees it."""
    class _FakeCrew:
        def __init__(self, **kw):
            pass

        def kickoff(self):
            return "   "                      # whitespace only

    class _FakeTask:
        def __init__(self, **kw):
            pass

    import crewai

    monkeypatch.setattr(crewai, "Crew", _FakeCrew)
    monkeypatch.setattr(crewai, "Task", _FakeTask)
    # Call once, no sleeping.
    monkeypatch.setattr(resilience, "retry_call", lambda fn, **kw: fn())

    with pytest.raises(Exception) as excinfo:
        _run_crew(object(), "d", "e", None, label="t")
    assert "empty" in str(excinfo.value).lower()


def test_empty_response_is_classified_transient():
    """A flake must be retryable; a bad key must not be."""
    assert is_transient(ValueError("LLM returned None or empty response"))
    assert is_transient(Exception("429 Too Many Requests"))
    assert not is_transient(Exception("401 Unauthorized: invalid api key"))
    assert not is_transient(Exception("413 Payload Too Large"))
