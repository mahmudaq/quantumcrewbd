"""Retry / transient-failure behaviour.

The live failure this guards against: a 365-second five-agent run was destroyed
by one empty response from the provider on the final (reviewer) call. Four
dossiers had already been produced. There was no retry anywhere in the
pipeline.
"""
from __future__ import annotations

import pytest

from orchestration.resilience import is_transient, retry_call


class FakeSleep:
    """Records requested delays instead of actually sleeping."""

    def __init__(self):
        self.delays: list[float] = []

    def __call__(self, d: float) -> None:
        self.delays.append(d)


class TestClassification:
    def test_the_observed_empty_response_is_transient(self):
        exc = ValueError("Invalid response from LLM call - None or empty.")
        assert is_transient(exc) is True

    def test_bare_empty_response_is_transient(self):
        assert is_transient(RuntimeError("Received None or empty response")) is True

    @pytest.mark.parametrize("msg", [
        "429 Too Many Requests",
        "rate limit exceeded",
        "503 Service Unavailable",
        "502 Bad Gateway",
        "504 Gateway Timeout",
        "500 Internal Server Error",
        "Connection reset by peer",
        "Read timed out",
    ])
    def test_retryable_provider_errors(self, msg):
        assert is_transient(RuntimeError(msg)) is True

    @pytest.mark.parametrize("msg", [
        "401 Unauthorized",
        "Invalid 'Authorization' header or token",
        "403 Forbidden",
        "Invalid API key provided",
    ])
    def test_auth_failures_are_permanent(self, msg):
        """A bad key never fixes itself — retrying burns 3x the wall clock."""
        assert is_transient(RuntimeError(msg)) is False

    @pytest.mark.parametrize("msg", [
        "413 Payload Too Large",
        "400 Bad Request",
        "maximum context length exceeded",
        "too many tokens in request",
    ])
    def test_payload_and_context_errors_are_permanent(self, msg):
        assert is_transient(RuntimeError(msg)) is False

    def test_413_wins_over_an_incidental_500_mention(self):
        """Permanent markers are checked first — payload size is not retryable."""
        msg = "413 request too large; the server returned 500 after rejecting it"
        assert is_transient(RuntimeError(msg)) is False

    def test_unknown_errors_are_not_retried(self):
        assert is_transient(KeyError("some_unexpected_key")) is False

    def test_does_not_leak_secrets_into_the_check(self):
        """Classification must not depend on any credential-shaped content."""
        assert is_transient(RuntimeError("openai/gpt-oss-120b failed")) is False


class TestRetrySucceeds:
    def test_succeeds_on_first_attempt_without_retrying(self):
        calls = []
        sleep = FakeSleep()

        def fn():
            calls.append(1)
            return "ok"

        assert retry_call(fn, sleep=sleep) == "ok"
        assert len(calls) == 1 and sleep.delays == []

    def test_recovers_from_one_transient_failure(self):
        """The exact live scenario: one flake, then success."""
        calls = []

        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("Invalid response from LLM call - None or empty.")
            return "dossier"

        assert retry_call(fn, sleep=FakeSleep()) == "dossier"
        assert len(calls) == 2

    def test_recovers_from_two_consecutive_transient_failures(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("503 Service Unavailable")
            return "ok"

        assert retry_call(fn, attempts=3, sleep=FakeSleep()) == "ok"
        assert len(calls) == 3

    def test_backoff_is_exponential_and_jittered(self):
        sleep = FakeSleep()

        def fn():
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            retry_call(fn, attempts=4, base_delay=2.0, sleep=sleep)

        assert len(sleep.delays) == 3          # no sleep after the final failure
        # 2, 4, 8 with up to +25% jitter
        assert 2.0 <= sleep.delays[0] <= 2.5
        assert 4.0 <= sleep.delays[1] <= 5.0
        assert 8.0 <= sleep.delays[2] <= 10.0
        assert sleep.delays == sorted(sleep.delays)

    def test_max_delay_is_respected(self):
        sleep = FakeSleep()

        def fn():
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            retry_call(fn, attempts=6, base_delay=10.0, max_delay=15.0, sleep=sleep)

        assert all(d <= 15.0 * 1.25 for d in sleep.delays)


class TestRetryFailsLoudly:
    def test_permanent_failure_raises_immediately_without_sleeping(self):
        calls, sleep = [], FakeSleep()

        def fn():
            calls.append(1)
            raise RuntimeError("401 Unauthorized")

        with pytest.raises(RuntimeError) as e:
            retry_call(fn, label="reviewer", sleep=sleep)

        assert len(calls) == 1, "must not retry a 401"
        assert sleep.delays == []
        assert "not retryable" in str(e.value)

    def test_exhausting_attempts_raises_with_the_count(self):
        calls = []

        def fn():
            calls.append(1)
            raise RuntimeError("503 Service Unavailable")

        with pytest.raises(RuntimeError) as e:
            retry_call(fn, attempts=3, label="reviewer", sleep=FakeSleep())

        assert len(calls) == 3
        assert "3/3" in str(e.value)
        assert "still failing" in str(e.value)

    def test_error_names_the_agent_so_the_next_debugging_session_is_short(self):
        def fn():
            raise RuntimeError("503 Service Unavailable")

        with pytest.raises(RuntimeError) as e:
            retry_call(fn, attempts=1, label="reviewer", sleep=FakeSleep())

        assert "reviewer" in str(e.value)

    def test_original_exception_is_chained(self):
        original = ValueError("Invalid response from LLM call - None or empty.")

        def fn():
            raise original

        with pytest.raises(RuntimeError) as e:
            retry_call(fn, attempts=1, sleep=FakeSleep())

        assert e.value.__cause__ is original

    def test_on_retry_hook_fires_once_per_retry(self):
        events = []

        def fn():
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            retry_call(fn, attempts=3, sleep=FakeSleep(),
                       on_retry=lambda a, e, d: events.append((a, d)))

        assert [a for a, _ in events] == [1, 2]

    def test_a_failing_hook_never_masks_the_real_error(self):
        def boom(a, e, d):
            raise KeyError("hook is broken")

        def fn():
            raise RuntimeError("timeout")

        with pytest.raises(RuntimeError, match="timeout"):
            retry_call(fn, attempts=2, sleep=FakeSleep(), on_retry=boom)


class TestWiredIntoThePipeline:
    """The agents must actually go through the retry path."""

    def test_all_five_agents_pass_a_label(self):
        import inspect

        from orchestration import pipeline

        src = inspect.getsource(pipeline)
        for agent in ("analyzer", "market_intel", "resource_planner",
                      "writer", "reviewer"):
            assert f'label="{agent}"' in src, f"{agent} call site is unlabelled"

    def test_run_crew_uses_retry_and_rejects_empty_output(self):
        import inspect

        from orchestration import pipeline

        src = inspect.getsource(pipeline._run_crew)
        assert "retry_call" in src
        assert "empty response" in src.lower(), \
            "empty output must be turned into an error so it can be retried"

    def test_no_double_attempt_helpers_that_bypass_retry(self):
        """Guard against a future agent calling crew.kickoff() directly.

        Counts real call sites, ignoring comments and docstrings — the module
        explains the pattern in prose, and prose is not a call site.
        """
        import ast
        import inspect

        from orchestration import pipeline

        tree = ast.parse(inspect.getsource(pipeline))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "kickoff"
        ]
        assert len(calls) == 1, (
            f"exactly one kickoff() call site is allowed (inside _once); "
            f"found {len(calls)}"
        )
