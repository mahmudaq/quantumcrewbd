"""Transient-failure resilience for LLM crew calls.

Why this module exists
----------------------
A live five-agent run takes ~365 s and makes five separate LLM calls. The
provider (CommandCode) intermittently returns an *empty* response — observed
as::

    Received None or empty response from LLM call.
    ValueError: Invalid response from LLM call - None or empty.

A single one of those flakes destroyed the entire run — four agents had already
produced valid dossiers, and the reviewer's flake threw all of it away. That is
not a model problem, it is an orchestration problem: **there was no retry
logic anywhere in the pipeline.**

CrewAI does not help here. ``crewai.LLM.__init__`` accepts no ``max_retries``
and no ``timeout`` (verified against 1.15.23), so the retry has to live in our
own call path. There is exactly one choke point — ``_run_crew`` — which every
agent passes through, so wrapping it covers all five agents.

Classification matters more than retrying
-----------------------------------------
Retrying a deterministic failure is worse than useless: it burns 3x the wall
clock to reach the same error, and on a 6-minute pipeline that is real damage.
So transient and permanent failures are separated deliberately:

* **Transient** — empty/None response, 429, 5xx, connection reset, timeout.
  Retry: the next attempt may well succeed.
* **Permanent** — 401/403 (bad or missing key), 400 (malformed request), 413
  (prompt over the provider's token limit). Do not retry; fail immediately and
  say why. A 413 in particular will never succeed on a retry, and the honest
  fix is to shrink the prompt.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

#: Substrings that identify a *transient* failure, lower-cased for matching.
#:
#: Deliberately substring-based rather than exception-class-based: the error
#: surfaces as a ``ValueError`` from CrewAI, an ``openai.APIStatusError``, or a
#: raw ``httpx`` transport error depending on where in the stack it dies. The
#: message is the only stable common denominator.
TRANSIENT_MARKERS: tuple[str, ...] = (
    "none or empty",          # the observed CommandCode flake
    "empty response",
    "empty completion",
    "no response",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection error",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "internal server error",
    "rate limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
)

#: Substrings that identify a *permanent* failure — never worth retrying.
#:
#: Checked BEFORE the transient markers, because some of these strings also
#: contain digits that appear in the transient list (e.g. a 413 message may
#: mention 500 elsewhere in the body).
PERMANENT_MARKERS: tuple[str, ...] = (
    "401",
    "403",
    "unauthorized",
    "invalid api key",
    "invalid 'authorization'",
    "authentication",
    "permission denied",
    "400",
    "bad request",
    "413",
    "payload too large",
    "context length",
    "maximum context",
    "too many tokens",
    "request too large",
)


def is_transient(exc: BaseException) -> bool:
    """Return True if ``exc`` looks like a failure worth retrying.

    Permanent markers win: a message that mentions both 413 and 500 is a
    payload-size problem, which a retry cannot fix.
    """
    msg = f"{type(exc).__name__}: {exc}".lower()

    if any(m in msg for m in PERMANENT_MARKERS):
        return False
    if any(m in msg for m in TRANSIENT_MARKERS):
        return True

    # Unknown failures: do not retry. A blind retry on an unclassified error is
    # how a pipeline turns one bug into three identical slow bugs.
    return False


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 20.0,
    label: str = "call",
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn`` with bounded retries on transient failures.

    Args:
        fn: Zero-argument callable to invoke.
        attempts: Total attempts (not retries). 3 means one try + two retries.
        base_delay: Delay before the first retry, in seconds.
        max_delay: Ceiling for the backoff.
        label: Name used in the raised error, so a failure names its agent.
        on_retry: Optional hook ``(attempt, exc, delay)`` — used by the event
            bridge so the UI can show "agent retrying".
        sleep: Injectable for tests.

    Returns:
        Whatever ``fn`` returns on its first successful attempt.

    Raises:
        The original exception, wrapped with the attempt count and the reason
        it was or was not retried. The message deliberately names the agent and
        the last error so the next debugging session starts with facts.
    """
    attempts = max(1, attempts)
    last: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except BaseException as exc:              # noqa: BLE001 - re-raised below
            last = exc
            transient = is_transient(exc)
            is_last = attempt >= attempts

            if not transient or is_last:
                why = (
                    "not retryable (classified permanent)"
                    if not transient
                    else f"still failing after {attempts} attempts"
                )
                raise RuntimeError(
                    f"{label} failed on attempt {attempt}/{attempts} — {why}. "
                    f"Last error: {type(exc).__name__}: {exc}"
                ) from exc

            # Exponential backoff with jitter, so several agents failing at once
            # do not retry in lockstep against the same rate limit.
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay += random.uniform(0, delay * 0.25)

            if on_retry:
                try:
                    on_retry(attempt, exc, delay)
                except Exception:                 # noqa: BLE001 - never fatal
                    pass
            sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise RuntimeError(f"{label} failed with no attempts made") from last
