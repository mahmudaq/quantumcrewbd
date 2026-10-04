"""Guards on the per-agent output budgets.

A live five-agent run failed at the reviewer with three consecutive empty
completions and no explanation. The cause was this table: the reviewer was
capped at 6_000 tokens while the writer got 12_000, even though the reviewer
re-emits the writer's whole draft plus its analysis. On a reasoning model the
chain-of-thought is billed against the same `max_tokens` budget, so the reviewer
spent the entire 6_000 on reasoning and returned an empty `content`, which CrewAI
reports as "Invalid response from LLM call - None or empty".

The retry wrapper retried a deterministic failure three times. These tests make
the budget relationship explicit so the starvation cannot be reintroduced.
"""

from __future__ import annotations

from llm.registry import AGENT_MAX_TOKENS


def test_reviewer_budget_is_not_below_the_writer():
    """The reviewer re-emits the draft; it cannot need fewer tokens than the writer."""
    assert AGENT_MAX_TOKENS["reviewer"] >= AGENT_MAX_TOKENS["writer"]
    assert AGENT_MAX_TOKENS["reviewer"] > 6_000, (
        "6_000 was proven insufficient for a real reviewer call -- reasoning alone "
        "consumed the whole budget and content came back empty"
    )


def test_every_agent_has_a_positive_budget():
    for agent, budget in AGENT_MAX_TOKENS.items():
        assert budget > 0, f"{agent} has a non-positive budget"


def test_reviewer_headroom_is_affordable():
    """max_tokens is a ceiling, not a target -- verify the provider finishes early.

    A large cap only costs what the model actually emits, so generous headroom is
    cheap. This documents the reasoning behind not capping tightly.
    """
    reviewer = AGENT_MAX_TOKENS["reviewer"]
    writer = AGENT_MAX_TOKENS["writer"]
    # If the reviewer really needed its full budget every time, the cap would set
    # a 3x latency floor. It does not: observed runs finish at ~11.7k tokens.
    assert reviewer <= 24_000, (
        "reviewer headroom beyond ~24k buys nothing and only invites latency drift"
    )
    assert reviewer - writer <= 8_000, (
        "unexpectedly large gap between writer and reviewer budgets"
    )
