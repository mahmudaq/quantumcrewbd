# Agent token budgets

Every agent has an output cap in `AGENT_MAX_TOKENS` (`llm/registry.py`). The cap
is the main latency lever in this pipeline: wall-clock time is output volume
divided by throughput, and every model on the provider runs ~100-110 tok/s.

The caps are **ceilings, not targets**. A run that finishes early costs only what
it actually emitted, so generous headroom is nearly free — and a cap set below
what an agent actually produces is a hard failure, not a slow run.

## The failure this table caused

A live five-agent run failed at the reviewer with three consecutive:

```
Received None or empty response from LLM call.
Invalid response from LLM call - None or empty.
```

It was recorded as provider flakiness, and a retry wrapper was built to survive
it. Retrying changed nothing, because the failure is deterministic.

The reviewer was capped at **6,000** while the writer got **12,000** — even though
the reviewer's output is a *superset* of the writer's: it re-emits the entire
corrected proposal as `final_proposal_text`, and it reasons about the draft first.

The provider serves a **reasoning model**. Responses carry a `reasoning_content`
field, and the chain-of-thought is billed against the same `max_tokens` budget as
the visible content. At 6,000 the reasoning alone consumed everything:

Measured against the provider with a reviewer-shaped prompt (82k-char draft,
"assess this and re-emit it corrected"):

| `max_tokens` | `finish_reason` | content | reasoning | result |
|---|---|---|---|---|
| 6,000 | `length` | **0 chars** | 27,891 chars | 🔴 empty completion |
| 12,000 | `length` | 26,846 chars | 28,603 chars | ✅ |
| 20,000 | `stop` | 3,775 chars | 49,914 chars | ✅ (finished early) |

At 6,000 the budget was exhausted on reasoning and `content` came back
zero-length. Three retries produced three empties. The retry wrapper is still
worth keeping for genuine flakes and 429s, but it cannot fix a starved budget and
should not be credited with one.

## Rules

1. **Never cap an agent below what it actually emits.** Measure first.
2. **A re-emitting agent needs at least as much as the agent it re-emits.**
   The reviewer must stay ≥ the writer. Pinned in `tests/test_token_budgets.py`.
3. **Reasoning tokens count against the cap.** On a reasoning model, budget for
   the chain-of-thought *plus* the visible answer.
4. **An empty completion is a signal, not noise.** It usually means the budget
   ran out mid-reasoning. Check the cap before adding retries.

## Current budgets

| Agent | Cap | Why |
|---|---|---|
| `analyzer` | 8,000 | Structured JSON over every mandatory criterion; truncation silently drops compliance requirements |
| `market_intel` | 4,000 | Short structured dossier |
| `resource_planner` | 6,000 | Structured dossier, tool-derived |
| `writer` | 12,000 | Long-form prose draft |
| `reviewer` | 20,000 | Re-emits the writer's draft **and** reasons about it |

Override per agent with `LLM_MAX_TOKENS_<AGENT>`, or globally with
`LLM_MAX_TOKENS`. Overrides win over the table above.
