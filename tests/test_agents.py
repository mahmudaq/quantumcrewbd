"""Gate 3 — agent contract tests.

What Gate 3 requires: "each agent's declared output keys match the downstream
consumer's expected input keys. Run each agent once against a fixture; validate
JSON parses into its model."

The second half needs live LLM calls and lives in the Gate-3 live script. What
runs here is everything that can be proven without a network:

  * prompts are constructible and carry the grounding facts
  * the deterministic pre-extraction reaches the analyzer prompt
  * writer section headings come from the tender, not a hardcoded list
  * reviewer arithmetic overrides the model's, and mismatch flags are honest
  * every parse_dossier rejects garbage rather than silently returning an
    empty dossier
"""
from __future__ import annotations

import json

import pytest

from agents import analyzer, market_intel, resource_planner, reviewer, writer
from models.dossiers import (
    RFPComplianceDossier,
    ResourceAndConsortiumDossier,
)
from parsing.tech6 import PART_HEADINGS

# Reuse the verbatim real excerpts from the datasheet tests.
from tests.test_datasheet import DOC1_DATASHEET, DOC3_EVAL_TABLE


# --------------------------------------------------------------------------- #
# Agent 1 — analyzer
# --------------------------------------------------------------------------- #

class TestAnalyzer:
    def test_pre_extract_finds_the_real_pass_mark(self):
        """The whole R-11 fix: the prompt is grounded, not left to search."""
        facts = analyzer.pre_extract(DOC1_DATASHEET)
        assert facts["technical_pass_mark"] == 70
        assert facts["pass_mark_evidence"]
        assert facts["data_sheet_found"] is True

    def test_pre_extract_doc3(self):
        facts = analyzer.pre_extract(DOC3_EVAL_TABLE)
        assert facts["technical_pass_mark"] == 45

    def test_prompt_carries_the_extracted_facts(self):
        p = analyzer.build_prompt(DOC1_DATASHEET, "Test Project", "PHE")
        assert "seventy (70)" in p or '"technical_pass_mark": 70' in p
        assert "Test Project" in p
        assert "PHE" in p

    def test_prompt_forbids_fabrication(self):
        p = analyzer.build_prompt(DOC1_DATASHEET)
        assert "Never invent" in p

    def test_prompt_includes_a_schema(self):
        p = analyzer.build_prompt(DOC1_DATASHEET)
        assert "detected_framework" in p

    def test_prompt_truncates_a_huge_tender(self):
        p = analyzer.build_prompt("x" * 200_000)
        assert len(p) < 120_000, "tender text not bounded — prompt would blow the context"

    def test_parse_plain_json(self):
        d = analyzer.parse_dossier(json.dumps({
            "detected_framework": "PPRA SBD", "technical_pass_mark": 45}))
        assert d.detected_framework == "PPRA SBD" and d.technical_pass_mark == 45.0

    def test_parse_fenced_json(self):
        d = analyzer.parse_dossier('```json\n{"detected_framework": "ADB QCBS"}\n```')
        assert d.detected_framework == "ADB QCBS"

    def test_parse_json_embedded_in_prose(self):
        d = analyzer.parse_dossier(
            'Here is my analysis:\n{"detected_framework": "World Bank SPD"}\nDone.')
        assert d.detected_framework == "World Bank SPD"

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            analyzer.parse_dossier("")

    def test_parse_no_json_raises(self):
        """Must raise, not return an empty dossier that looks like success."""
        with pytest.raises(ValueError, match="no JSON"):
            analyzer.parse_dossier("I could not analyse this document.")

    def test_empty_tender_still_builds_a_prompt(self):
        assert analyzer.build_prompt("") != ""


# --------------------------------------------------------------------------- #
# Agent 2 — market intel
# --------------------------------------------------------------------------- #

class TestMarketIntel:
    def test_prompt_includes_scope_and_roles(self):
        p = market_intel.build_prompt("Design review", "PHE Lakki", "Pakistan",
                                      "Water", ["Team Leader", "GIS Analyst"])
        assert "Design review" in p
        assert "Team Leader" in p and "GIS Analyst" in p

    def test_prompt_handles_missing_everything(self):
        p = market_intel.build_prompt("")
        assert "not supplied" in p

    def test_parse(self):
        d = market_intel.parse_dossier(json.dumps({
            "target_jurisdiction": "Pakistan",
            "rate_benchmarks": [{"role": "Team Leader", "low": 200, "high": 400}],
            "win_themes": ["local presence"]}))
        assert d.rate_benchmarks[0].role == "Team Leader"
        assert d.rate_benchmarks[0].low == 200


# --------------------------------------------------------------------------- #
# Agent 3 — resource planner
# --------------------------------------------------------------------------- #

class TestResourcePlanner:
    def test_prompt_lists_mandates_and_vacancy_rule(self):
        p = resource_planner.build_prompt(
            [{"role": "Team Leader", "min_years": 15}],
            [{"requirement": "ISO 27001"}],
            "scope here", ["TECH-1", "TECH-6"])
        assert "Team Leader" in p and "ISO 27001" in p
        assert "INTERNAL BENCH VACANCY" in p, "the go-external trigger must be in the prompt"
        assert "TECH-6" in p

    def test_prompt_forbids_filling_gaps_with_fabrication(self):
        p = resource_planner.build_prompt([{"role": "X"}], [])
        assert "unfilled_roles" in p
        assert "Never invent" in p

    def test_prompt_handles_empty_mandates(self):
        p = resource_planner.build_prompt([], [])
        assert "none specified" in p

    def test_accepts_model_objects_not_just_dicts(self):
        class Stub:
            def model_dump(self):
                return {"role": "Team Leader", "min_years": 15}
        p = resource_planner.build_prompt([Stub()], [])
        assert "Team Leader" in p

    def test_parse_preserves_unfilled_roles(self):
        d = resource_planner.parse_dossier(json.dumps({
            "key_personnel_table": [{"role": "TL", "candidate_name": "A",
                                     "source": "internal", "meets_mandate": True}],
            "unfilled_roles": ["CISSP Specialist"],
            "total_mandays": 150}))
        assert d.unfilled_roles == ["CISSP Specialist"]
        assert d.total_mandays == 150


# --------------------------------------------------------------------------- #
# Agent 4 — writer
# --------------------------------------------------------------------------- #

class TestWriter:
    def test_world_bank_gets_six_tech_forms(self):
        h = writer.required_headings("World Bank SPD")
        assert len(h) == 6
        assert all(s.startswith("Form TECH-") for s in h)
        assert "TECH-6" in h[5]

    def test_adb_gets_the_same_form_set(self):
        assert writer.required_headings("ADB QCBS") == writer.required_headings("World Bank SPD")

    def test_commercial_gets_commercial_sections(self):
        h = writer.required_headings("Custom Commercial")
        assert "Executive Summary" in h
        assert not any(s.startswith("Form TECH-") for s in h)

    def test_tender_form_list_wins_over_template(self):
        """A tender citing only TECH-2 gets only TECH-2, not all six."""
        h = writer.required_headings("World Bank SPD", ["TECH-2"])
        assert len(h) == 1 and "TECH-2" in h[0]

    def test_prompt_has_verbatim_headings(self):
        p = writer.build_prompt({"detected_framework": "World Bank SPD"}, {})
        for heading in writer.WB_ADB_FORMS:
            assert heading[0] in p

    def test_prompt_accepts_model_objects(self):
        d = RFPComplianceDossier(detected_framework="PPRA SBD", mandatory_forms=["TECH-1"])
        r = ResourceAndConsortiumDossier(total_mandays=99)
        p = writer.build_prompt(d, r)
        assert "PPRA SBD" in p and "99" in p

    def test_parse_backfills_full_markdown_from_sections(self):
        """A model that fills only `sections` still yields a usable document."""
        d = writer.parse_dossier(json.dumps({
            "sections": [{"heading": "Form TECH-1", "body": "Letter text"}]}))
        assert "## Form TECH-1" in d.full_markdown
        assert "Letter text" in d.full_markdown

    def test_parse_keeps_explicit_full_markdown(self):
        d = writer.parse_dossier(json.dumps({
            "full_markdown": "# Whole Doc", "sections": []}))
        assert d.full_markdown == "# Whole Doc"

    def test_section_headings_helper(self):
        d = writer.parse_dossier(json.dumps(
            {"sections": [{"heading": "A", "body": "x"}, {"heading": "B", "body": "y"}]}))
        assert d.section_headings() == ["A", "B"]


# --------------------------------------------------------------------------- #
# Agent 5 — reviewer
# --------------------------------------------------------------------------- #

class TestReviewer:
    CRITERIA = [
        {"criterion": "PEC registration", "mandatory": True, "pass_mark": 70},
        {"criterion": "ISO 27001", "mandatory": True},
    ]

    def test_deterministic_facts_do_not_score_unassessed_criteria(self):
        """'Required' is not 'failed' — pre-audit there is no score to compute.

        Scoring the tender's raw requirement list would report 0% for a
        perfectly good bid, since no verdicts exist yet.
        """
        facts = reviewer.deterministic_facts([], "text")
        assert "computed_compliance_score" not in facts
        assert facts["computed_total_mandays"] == 0.0

    def test_mandays_mismatch_is_flagged(self):
        phases = [{"phase": "A", "duration_days": 10, "fte": 2}]   # = 20
        facts = reviewer.deterministic_facts(phases, "text", stated_mandays=50)
        assert facts["computed_total_mandays"] == 20
        assert facts["mandays_mismatch"] is True

    def test_no_mismatch_when_totals_agree(self):
        phases = [{"phase": "A", "duration_days": 10, "fte": 2}]
        facts = reviewer.deterministic_facts(phases, "text", stated_mandays=20)
        assert facts["mandays_mismatch"] is False

    def test_detects_missing_statutory_clause(self):
        facts = reviewer.deterministic_facts([], "a draft with no clause")
        assert facts["statutory_clause_present"] is False

    def test_prompt_lists_all_eight_tech6_parts(self):
        p = reviewer.build_prompt("draft", self.CRITERIA)
        for part in PART_HEADINGS:
            assert part in p

    def test_prompt_states_pass_mark_or_warns_absence(self):
        p = reviewer.build_prompt("draft", self.CRITERIA)
        assert "NOT STATED" in p or "do not assume" in p.lower()

    def test_prompt_injects_computed_arithmetic(self):
        p = reviewer.build_prompt("draft", self.CRITERIA,
                                  phases=[{"phase": "A", "duration_days": 5, "fte": 1}])
        assert "computed_total_mandays" in p

    def test_prompt_asks_for_assessments_and_unverified_flag(self):
        p = reviewer.build_prompt("draft", self.CRITERIA)
        assert "criterion_assessments" in p
        assert "verified" in p and "not a pass" in p

    def test_parse_scores_the_reviewers_own_verdicts(self):
        """The model writes verdicts; Python counts them.

        A model-supplied score is discarded — the reviewer mis-adding its own
        tally is exactly the accuracy failure it exists to catch.
        """
        d = reviewer.parse_dossier(
            json.dumps({
                "compliance_score": 12.0,          # wrong on purpose
                "criterion_assessments": [
                    {"criterion": "PEC registration", "passed": True,
                     "dimension": "Evidence", "evidence": "attached at Annex A"},
                    {"criterion": "ISO 27001", "passed": False,
                     "dimension": "Completeness", "evidence": "not addressed"},
                ],
                "findings": [],
            }),
            phases=[{"phase": "A", "duration_days": 10, "fte": 2}],
            stated_mandays=50,
            draft_text="a draft",
        )
        assert d.compliance_score == 50.0, "model's wrong score was kept"
        assert d.criteria_passed == 1 and d.criteria_total == 2
        assert d.recomputed_total_mandays == 20
        assert d.mandays_mismatch is True

    def test_parse_without_assessments_leaves_score_alone(self):
        """No verdicts means no score — not a fabricated 0%."""
        d = reviewer.parse_dossier(json.dumps({"findings": []}))
        assert d.criteria_total == 0
        assert d.compliance_score == 0.0

    def test_parse_sets_missing_forms(self):
        d = reviewer.parse_dossier(
            json.dumps({"findings": []}),
            mandatory_forms=["TECH-1", "TECH-6"],
            draft_text="Form TECH-1 content only",
        )
        assert d.missing_forms == ["TECH-6"]

    def test_parse_keeps_narrative_findings(self):
        d = reviewer.parse_dossier(json.dumps({"findings": [
            {"dimension": "Accuracy", "severity": "blocker",
             "finding": "effort table does not reconcile", "verified": True}]}))
        assert len(d.blockers()) == 1

    def test_parse_records_unverified_findings(self):
        d = reviewer.parse_dossier(json.dumps({"findings": [
            {"dimension": "Evidence", "severity": "major",
             "finding": "cannot confirm the claimed completion date",
             "verified": False}]}))
        assert d.findings[0].verified is False


# --------------------------------------------------------------------------- #
# Cross-agent
# --------------------------------------------------------------------------- #

class TestAgentModuleSurface:
    """Every agent module must expose the same three entry points."""

    @pytest.mark.parametrize("mod", [analyzer, market_intel, resource_planner,
                                     writer, reviewer])
    def test_exposes_build_prompt_and_parse(self, mod):
        assert callable(getattr(mod, "build_prompt"))
        assert callable(getattr(mod, "parse_dossier"))

    @pytest.mark.parametrize("mod", [analyzer, market_intel, resource_planner,
                                     writer, reviewer])
    def test_has_role_goal_backstory(self, mod):
        for attr in ("ROLE", "GOAL", "BACKSTORY"):
            assert isinstance(getattr(mod, attr), str) and getattr(mod, attr)

    def test_builders_are_callable(self):
        """Constructing an Agent needs CrewAI; just assert the factory exists."""
        assert callable(analyzer.build_analyzer)
        assert callable(market_intel.build_market_intel)
        assert callable(resource_planner.build_resource_planner)
        assert callable(writer.build_writer)
        assert callable(reviewer.build_reviewer)
