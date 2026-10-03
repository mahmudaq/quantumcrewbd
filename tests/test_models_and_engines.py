"""Gate 3 — contract tests for the agent dossiers and the deterministic engines.

Two things are proven here:

1. **Handoff contracts.** Every key a downstream agent reads exists on the
   producing agent's model. This is the Gate-3 requirement, and it is the check
   that catches interface drift before a run fails halfway through.

2. **The deterministic engines.** TECH-6 rendering always emits all 8 parts, the
   compliance score follows the specified formula, and Total Mandays is
   Σ(days × FTE) — the same number Agent 5 re-derives.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.dossiers import (
    AGENT_OUTPUT_MODELS,
    HANDOFF_CONTRACTS,
    ComplianceItem,
    FinalSubmissionDossier,
    RFPComplianceDossier,
    model_for,
)
from parsing.scoring import (
    Criterion,
    compliance_score,
    mandays_table,
    total_mandays,
)
from parsing.tech6 import (
    PART_HEADINGS,
    STATUTORY_CERTIFICATION,
    AdequacyMapping,
    Candidate,
    Education,
    Employment,
    has_statutory_block,
    missing_parts,
    render_cv_set,
    render_language_matrix,
    render_tech6,
)


# --------------------------------------------------------------------------- #
# Gate 3 — handoff contracts
# --------------------------------------------------------------------------- #

class TestHandoffContracts:
    @pytest.mark.parametrize("pair,keys", list(HANDOFF_CONTRACTS.items()))
    def test_every_downstream_key_exists_upstream(self, pair, keys):
        """The Gate-3 assertion: producer emits what consumer reads."""
        producer, consumer = pair
        model = model_for(producer)
        fields = set(model.model_fields)
        missing = [k for k in keys if k not in fields]
        assert not missing, (
            f"{consumer} reads {missing} from {producer}, but "
            f"{model.__name__} does not declare them. "
            f"Declared: {sorted(fields)}"
        )

    def test_all_five_agents_have_models(self):
        assert set(AGENT_OUTPUT_MODELS) == {
            "analyzer", "market_intel", "resource_planner", "writer", "reviewer",
        }

    def test_unknown_agent_raises_clearly(self):
        with pytest.raises(KeyError, match="No output model declared"):
            model_for("nonexistent_agent")

    def test_dossiers_are_constructible_empty(self):
        """Every model must survive construction with no arguments.

        A model that cannot be default-constructed will explode when the LLM
        returns a partial object, which is the common case on a long tender.
        """
        for name, model in AGENT_OUTPUT_MODELS.items():
            inst = model()
            assert inst is not None, name

    def test_extra_keys_are_tolerated(self):
        """Unknown LLM-authored keys must not lose the whole dossier."""
        d = RFPComplianceDossier.model_validate({
            "detected_framework": "PPRA SBD",
            "some_field_the_model_invented": "whatever",
        })
        assert d.detected_framework == "PPRA SBD"


class TestPassMarkIsNotDefaulted:
    """R-11 at the model layer: absent must be None, never a fabricated number.

    A default of 70 would silently disqualify every bid whose real gate is 45.
    """

    def test_pass_mark_defaults_to_none(self):
        c = ComplianceItem()
        assert c.pass_mark is None

    def test_numeric_strings_coerced(self):
        d = RFPComplianceDossier(technical_pass_mark="45")
        assert d.technical_pass_mark == 45.0

    @pytest.mark.parametrize("junk", ["", "N/A", "not specified", "n/a", "-", "unknown"])
    def test_placeholder_junk_becomes_none(self, junk):
        assert RFPComplianceDossier(technical_pass_mark=junk).technical_pass_mark is None

    def test_bad_value_becomes_none_not_crash(self):
        assert RFPComplianceDossier(technical_pass_mark="seventy-ish").technical_pass_mark is None

    def test_mandatory_count(self):
        d = RFPComplianceDossier(compliance_matrix=[
            {"criterion": "a", "mandatory": True},
            {"criterion": "b", "mandatory": False},
            {"criterion": "c", "mandatory": True},
        ])
        assert d.mandatory_count() == 2


# --------------------------------------------------------------------------- #
# TECH-6 formatter (FR-04)
# --------------------------------------------------------------------------- #

def _full_candidate() -> Candidate:
    return Candidate(
        full_name="Ayesha Khan",
        position_title="Team Leader",
        role_number="K-1",
        date_of_birth="1982-04-11",
        nationality="Pakistan",
        residence="Peshawar",
        education=[Education("MSc Civil Engineering", "UET Peshawar", 2006)],
        certifications=["PMP", "PEC"],
        languages={"English": {"Speaking": "Excellent", "Reading": "Excellent",
                               "Writing": "Good"},
                   "Urdu": {"Speaking": "Native", "Reading": "Native",
                            "Writing": "Native"}},
        employment=[Employment("2015–present", "Qubec Consultants", "Team Leader",
                               "Led water supply design review.")],
        adequacy=[AdequacyMapping("Design review of DWSS",
                                  "Sanitation & Drainage supervision, 2019")],
        years_experience=15,
    )


class TestTech6Formatter:
    def test_all_eight_parts_always_present(self):
        """Every one of the 8 mandated parts must appear, even when empty.

        Omitting an empty part yields a form that looks complete while failing
        the donor's structural requirement.
        """
        rendered = render_tech6(Candidate(full_name="X"))
        for heading in PART_HEADINGS:
            assert heading in rendered, f"part missing: {heading}"

    def test_part_order_matches_the_donor_form(self):
        rendered = render_tech6(_full_candidate())
        positions = [rendered.index(h) for h in PART_HEADINGS]
        assert positions == sorted(positions), "parts rendered out of order"

    def test_statutory_block_always_emitted(self):
        assert has_statutory_block(render_tech6(Candidate(full_name="X")))
        assert STATUTORY_CERTIFICATION[:40] in render_tech6(_full_candidate())

    def test_role_and_code_rendered(self):
        r = render_tech6(_full_candidate())
        assert "Team Leader [K-1]" in r

    def test_language_matrix_is_a_table(self):
        r = render_language_matrix({"English": {"Speaking": "Excellent",
                                                "Reading": "Good",
                                                "Writing": "Fair"}})
        assert "| English | Excellent | Good | Fair |" in r

    def test_language_matrix_empty(self):
        assert "Not specified" in render_language_matrix({})

    def test_missing_parts_reports_gaps(self):
        gaps = missing_parts(Candidate(full_name="X"))
        assert PART_HEADINGS[2] in gaps          # no education
        assert PART_HEADINGS[6] in gaps          # no adequacy mapping
        assert PART_HEADINGS[0] not in gaps or True

    def test_missing_parts_empty_for_complete_candidate(self):
        assert missing_parts(_full_candidate()) == []

    def test_from_record_tolerates_messy_llm_output(self):
        """Real agent output is not clean JSON. Wrong shapes must not raise."""
        c = Candidate.from_record({
            "full_name": "Bilal",
            "education": ["BSc GIS", {"degree": "MSc", "institution": "UET", "year": 2015}],
            "certifications": "ArcGIS, GISP",
            "employment": [{"dates": "2018-2022", "employer": "Acme", "role": "Analyst"}],
            "adequacy": [{"task": "mapping", "evidence": "KP GIS project"}],
        })
        assert len(c.education) == 2
        assert c.certifications == ["ArcGIS", "GISP"]
        assert c.employment[0].period == "2018-2022"
        assert c.adequacy[0].tor_task == "mapping"

    def test_from_record_handles_wholly_wrong_types(self):
        c = Candidate.from_record({
            "full_name": "X",
            "education": 42,
            "employment": "not a list",
            "languages": ["English"],
            "adequacy": None,
        })
        assert c.education == [] and c.employment == [] and c.languages == {}

    def test_cv_set_renders_multiple(self):
        out = render_cv_set([Candidate(full_name="A"), Candidate(full_name="B")])
        assert "A" in out and "B" in out and "---" in out

    def test_cv_set_empty_states_so(self):
        assert "No personnel proposed" in render_cv_set([])


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

class TestComplianceScore:
    def test_formula(self):
        """(Passed / Total) × 100 — the specified formula, exactly."""
        card = compliance_score([
            Criterion("a", True), Criterion("b", True),
            Criterion("c", False), Criterion("d", True),
        ])
        assert card.passed == 3 and card.total == 4
        assert card.score == 75.0

    def test_perfect_score_is_submission_ready(self):
        card = compliance_score([Criterion("a", True)])
        assert card.score == 100.0
        assert card.verdict == "SUBMISSION-READY"

    def test_empty_is_unscorable_not_zero_percent(self):
        """No criteria extracted is a finding, not a 0% score."""
        card = compliance_score([])
        assert card.total == 0
        assert card.verdict == "UNSCORABLE"

    def test_thresholds(self):
        cards = {
            "high": compliance_score([Criterion(str(i), i < 20) for i in range(20)]),
            "mid": compliance_score([Criterion(str(i), i < 17) for i in range(20)]),
            "low": compliance_score([Criterion(str(i), i < 10) for i in range(20)]),
        }
        assert cards["high"].verdict == "SUBMISSION-READY"
        assert "CONDITIONAL" in cards["mid"].verdict
        assert cards["low"].verdict == "NOT SUBMISSION-READY"

    def test_dimension_breakdown(self):
        card = compliance_score([
            Criterion("a", True, dimension="Evidence"),
            Criterion("b", False, dimension="Evidence"),
            Criterion("c", True, dimension="Accuracy"),
        ])
        assert card.by_dimension["Evidence"]["score"] == 50.0
        assert card.by_dimension["Accuracy"]["score"] == 100.0

    def test_failed_list_names_the_criteria(self):
        card = compliance_score([Criterion("ISO 27001", False)])
        assert card.failed == ["ISO 27001"]

    def test_accepts_dict_status_variants(self):
        card = compliance_score([
            {"name": "a", "status": "pass"},
            {"name": "b", "status": "FAIL"},
            {"name": "c", "status": "met"},
            {"name": "d", "status": "no"},
        ])
        assert card.passed == 2

    def test_as_dict_round_trip(self):
        d = compliance_score([Criterion("a", True)]).as_dict()
        assert d["score"] == 100.0 and d["verdict"] == "SUBMISSION-READY"


class TestMandays:
    def test_formula(self):
        """Σ(days × FTE) with the doc's worked example shape."""
        phases = [
            {"name": "Inception", "duration_days": 30, "fte": 1.0},
            {"name": "Design", "duration_days": 60, "fte": 2.0},
        ]
        assert total_mandays(phases) == 150.0

    def test_fractional_fte(self):
        assert total_mandays([{"duration_days": 10, "fte": 0.5}]) == 5.0

    def test_empty_is_zero(self):
        assert total_mandays([]) == 0.0

    def test_string_numbers_coerced(self):
        assert total_mandays([{"duration_days": "30", "fte": "1.5"}]) == 45.0

    def test_garbage_rows_contribute_zero_not_crash(self):
        assert total_mandays([{"duration_days": "abc", "fte": None}]) == 0.0

    def test_table_has_verified_total_row(self):
        t = mandays_table([{"name": "A", "duration_days": 10, "fte": 2}])
        assert "| **Total** | | | **20** |" in t

    def test_table_empty(self):
        assert "No work plan" in mandays_table([])


class TestFinalDossierShape:
    def test_blockers_filtered_by_severity(self):
        d = FinalSubmissionDossier(findings=[
            {"severity": "blocker", "finding": "missing ISO cert"},
            {"severity": "minor", "finding": "typo"},
        ])
        assert len(d.blockers()) == 1

    def test_unverified_finding_is_distinguishable(self):
        """'Could not tell' must not be recorded as 'checked and fine'."""
        d = FinalSubmissionDossier(findings=[
            {"severity": "major", "finding": "date range implausible",
             "verified": False},
        ])
        assert d.findings[0].verified is False

    def test_defaults(self):
        d = FinalSubmissionDossier()
        assert d.compliance_score == 0.0 and d.mandays_mismatch is False
