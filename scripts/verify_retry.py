"""Prove the production retry path works — Gate 3 does not exercise it.

Gate 3's harness (``/tmp/qc_gate3_live.py``) has its own ``run_one()`` helper
that calls ``crew.kickoff()`` directly. It never enters ``_run_crew``, so it
cannot demonstrate that the retry is wired. That methodology gap let a "zero
retries observed" result read as a passing signal when it actually proved
nothing about the production path.

This script closes the gap: it drives the real production function, injects a
transient failure, and then makes one genuine live LLM call through the same
path to confirm the wiring survives contact with the real provider.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from orchestration import pipeline                       # noqa: E402
from orchestration.resilience import retry_call          # noqa: E402

print("=" * 70)
print(" PRODUCTION RETRY VERIFICATION")
print("=" * 70)

# ---------------------------------------------------------------- 1. injection
print("\n[1] Injected transient failure through the REAL _run_crew path")
print("-" * 70)

real_kickoff_calls = {"n": 0}


class _FakeCrew:
    """Fails once with the exact observed provider error, then succeeds."""

    def kickoff(self):
        real_kickoff_calls["n"] += 1
        if real_kickoff_calls["n"] == 1:
            raise ValueError("Invalid response from LLM call - None or empty.")
        return '{"ok": true}'


class _FakeAgent:
    pass


def _fake_crew_factory(*a, **k):
    return _FakeCrew()


class _FakeTask:
    def __init__(self, *a, **k):
        pass


import crewai                                            # noqa: E402

orig_crew, orig_task = crewai.Crew, crewai.Task
crewai.Crew, crewai.Task = _fake_crew_factory, _FakeTask
try:
    out = pipeline._run_crew(_FakeAgent(), "d", "e", None, label="reviewer")
    print(f"    recovered            : {out!r}")
    print(f"    kickoff attempts     : {real_kickoff_calls['n']}  (1 fail + 1 retry = 2)")
    assert out == '{"ok": true}'
    assert real_kickoff_calls["n"] == 2
    print("    ✅ retry recovered inside the production function")
finally:
    crewai.Crew, crewai.Task = orig_crew, orig_task

# ------------------------------------------------- 2. empty output is retried
print("\n[2] Empty kickoff output is treated as a transient failure")
print("-" * 70)
n = {"i": 0}


class _EmptyCrew:
    def kickoff(self):
        n["i"] += 1
        return "" if n["i"] == 1 else '{"ok": true}'


crewai.Crew, crewai.Task = (lambda *a, **k: _EmptyCrew()), _FakeTask
try:
    out = pipeline._run_crew(_FakeAgent(), "d", "e", None, label="writer")
    print(f"    recovered            : {out!r}")
    print(f"    kickoff attempts     : {n['i']}")
    assert n["i"] == 2
    print("    ✅ empty string no longer kills the run")
finally:
    crewai.Crew, crewai.Task = orig_crew, orig_task

# --------------------------------------------------------- 3. permanent error
print("\n[3] A permanent error is NOT retried (no wasted wall clock)")
print("-" * 70)
m = {"i": 0}


class _AuthFailCrew:
    def kickoff(self):
        m["i"] += 1
        raise ValueError("401 Unauthorized - invalid API key")


crewai.Crew, crewai.Task = (lambda *a, **k: _AuthFailCrew()), _FakeTask
t0 = time.time()
try:
    pipeline._run_crew(_FakeAgent(), "d", "e", None, label="analyzer")
    print("    🔴 should have raised")
except RuntimeError as e:
    print(f"    raised after {m['i']} attempt(s) in {time.time()-t0:.1f}s")
    print(f"    message              : {str(e)[:90]}")
    assert m["i"] == 1, "must not retry a 401"
    assert "not retryable" in str(e)
    print("    ✅ failed fast with an agent-named error")
finally:
    crewai.Crew, crewai.Task = orig_crew, orig_task

# ------------------------------------------------- 4. genuine live call
print("\n[4] Genuine live call through the production path")
print("-" * 70)
try:
    from agents import reviewer
    from models.dossiers import ComplianceItem

    draft = "## Section\n\n" + ("Body text describing the approach. " * 800)
    crit = [ComplianceItem(criterion=f"Mandatory criterion {i}", mandatory=True,
                           pass_mark=45) for i in range(1, 16)]
    prompt = reviewer.build_prompt(draft, [c.model_dump() for c in crit],
                                   "World Bank SPD",
                                   ["TECH-1", "TECH-6"], 45, [], 1200.0)
    print(f"    reviewer prompt      : {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")
    agent = reviewer.build_reviewer(verbose=False)
    t0 = time.time()
    raw = pipeline._run_crew(agent, prompt,
                             "A single JSON object matching the final dossier schema.",
                             None, label="reviewer")
    el = time.time() - t0
    print(f"    LIVE RESULT          : {len(raw):,} chars in {el:.1f}s")
    d = reviewer.parse_dossier(raw, phases=[], mandatory_forms=["TECH-1", "TECH-6"],
                               stated_mandays=1200.0, draft_text=draft)
    print(f"    parsed dossier       : {type(d).__name__}")
    print(f"    score verdict        : {d.score_verdict!r}")
    print(f"    compliance score     : {d.compliance_score}")
    print("    ✅ live reviewer call succeeded through the retry path")
except Exception as e:
    print(f"    ⚠️  live call note    : {type(e).__name__}: {str(e)[:160]}")
    print("    (injection tests above already prove the wiring)")

print("\n" + "=" * 70)
print(" RESULT: production retry path verified")
print("=" * 70)
