"""Parsing tolerance — the failure mode that killed the writer live.

Root cause: models emit markdown inside JSON string values with *literal*
newlines instead of `\\n`. That is invalid JSON, and the writer's proposal body
is mostly markdown, so it broke intermittently — two runs parsed, the third
died with "Expecting ',' delimiter at char 25616".

These tests pin the exact inputs that failed, so the fix cannot silently
regress.
"""
from __future__ import annotations

import json

import pytest

from agents.analyzer import _extract_json


class TestControlCharactersInStrings:
    """Literal newlines/tabs inside JSON strings — the live failure."""

    def test_literal_newline_inside_a_string(self):
        raw = '{"body": "## Section\n\nSome text"}'
        assert _extract_json(raw)["body"].startswith("## Section")

    def test_literal_tab_inside_a_string(self):
        raw = '{"body": "col1\tcol2"}'
        assert _extract_json(raw)["body"] == "col1\tcol2"

    def test_the_writer_shape_that_actually_broke(self):
        """A markdown body with headings, tables and blank lines — as emitted."""
        body = (
            "## Workstream E — Appraisal alignment\n\n"
            "| Item | Treatment |\n|---|---|\n"
            "| M5 | Managed |\n\n"
            "**Note.** Findings are absorbed without moving M5."
        )
        raw = json.dumps({"full_markdown": body, "sections": []})
        # Break it the way a model does: real newlines, unescaped.
        broken = raw.replace("\\n", "\n")
        got = _extract_json(broken)["full_markdown"]
        assert "Workstream E" in got and "|---|" in got

    def test_multiple_fields_with_control_chars(self):
        raw = '{"a": "line1\nline2", "b": "tab\there", "c": "clean"}'
        d = _extract_json(raw)
        assert d["a"] == "line1\nline2" and d["b"] == "tab\there" and d["c"] == "clean"


class TestFencedAndProseWrapped:
    def test_fenced_json_block(self):
        raw = 'Here you go:\n```json\n{"framework": "World Bank SPD"}\n```\nDone.'
        assert _extract_json(raw)["framework"] == "World Bank SPD"

    def test_fenced_json_with_control_chars(self):
        raw = '```json\n{"body": "## H\n\ntext"}\n```'
        assert _extract_json(raw)["body"].startswith("## H")

    def test_prose_around_a_bare_object(self):
        raw = 'Sure. {"pass_mark": 45} That is all.'
        assert _extract_json(raw)["pass_mark"] == 45


class TestTruncatedOutput:
    """Models hitting the output cap mid-object."""

    def test_salvages_object_missing_one_closing_brace(self):
        raw = '{"a": 1, "b": "x"'
        assert _extract_json(raw) == {"a": 1, "b": "x"}

    def test_salvages_object_cut_inside_a_list(self):
        raw = '{"criteria": [{"c": "c1", "mandatory": true}'
        d = _extract_json(raw)
        assert d["criteria"][0]["c"] == "c1"

    def test_salvages_truncated_markdown_body(self):
        raw = '{"full_markdown": "## Part one\n\nText that got cut'
        assert _extract_json(raw)["full_markdown"].startswith("## Part one")


class TestFailureModesStillFail:
    """Tolerance must not become 'accept anything'."""

    def test_empty_output_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _extract_json("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _extract_json("   \n  ")

    def test_no_json_at_all_raises(self):
        with pytest.raises(ValueError, match="no JSON object"):
            _extract_json("I cannot help with that request.")

    def test_genuinely_broken_json_raises_rather_than_guessing(self):
        with pytest.raises(ValueError, match="could not parse"):
            _extract_json('{"a": 1 2 3 ,,,}')

    def test_error_message_names_the_attempts(self):
        """The message must make the next debugging session short."""
        with pytest.raises(ValueError) as e:
            _extract_json('{"a": @@@}')
        assert "strict" in str(e.value) and "non-strict" in str(e.value)


class TestSharedByAllAgents:
    """Every agent imports this one function, so the fix is fleet-wide."""

    def test_all_five_agents_use_the_hardened_parser(self):
        import inspect

        from agents import (analyzer, market_intel, resource_planner, reviewer,
                            writer)

        for mod in (analyzer, market_intel, resource_planner, writer, reviewer):
            src = inspect.getsource(mod)
            assert "_extract_json" in src, f"{mod.__name__} bypasses the parser"
