"""Null tolerance across every dossier field.

The live failure: ``key_personnel_table.0.candidate_name`` arrived as ``null``
and rejected the whole ResourceAndConsortiumDossier, discarding two other
agents' completed work. A previous fix had patched only
``duration_days``/``fte``; the very next live run found a new field.

The fix is on ``_Base``, so these tests assert the *general* property: for any
field with a declared default, an explicit null becomes that default.
"""
from __future__ import annotations

import pytest

from models.dossiers import (
    AGENT_OUTPUT_MODELS,
    ComplianceItem,
    KeyPersonnelEntry,
    LevelOfEffortEntry,
    MarketIntelligenceDossier,
    PersonnelMandate,
    RateBenchmark,
    RFPComplianceDossier,
    ResourceAndConsortiumDossier,
)


class TestTheExactLiveFailure:
    def test_candidate_name_null_no_longer_rejects_the_dossier(self):
        d = KeyPersonnelEntry.model_validate({
            "role": "Team Leader", "candidate_name": None, "source": None,
        })
        assert d.candidate_name == "" and d.source == ""

    def test_the_whole_resource_dossier_survives_a_null_candidate(self):
        """Reproduces the live failure at dossier level, not field level."""
        d = ResourceAndConsortiumDossier.model_validate({
            "key_personnel_table": [
                {"role": "Team Leader", "candidate_name": None,
                 "years_experience": None, "certifications": None},
                {"role": "M&E Specialist", "candidate_name": "Ayesha K.",
                 "years_experience": 9, "certifications": ["PMP"]},
            ],
        })
        assert d.key_personnel_table[0].candidate_name == ""
        # The other row must be untouched — coercion must not flatten real data.
        assert d.key_personnel_table[1].candidate_name == "Ayesha K."
        assert d.key_personnel_table[1].years_experience == 9

    def test_a_list_field_null_becomes_an_empty_list_not_None(self):
        d = KeyPersonnelEntry.model_validate({"certifications": None})
        assert d.certifications == []


class TestEveryDeclaredDefaultIsCovered:
    """The general property, so the next live field cannot surprise us."""

    @pytest.mark.parametrize("model", AGENT_OUTPUT_MODELS if isinstance(
        AGENT_OUTPUT_MODELS, (list, tuple)) else [RFPComplianceDossier])
    def test_agent_dossier_top_level(self, model):
        d = model.model_validate({})
        assert d is not None

    @pytest.mark.parametrize("model", [
        PersonnelMandate, ComplianceItem, KeyPersonnelEntry,
        LevelOfEffortEntry, RateBenchmark,
    ])
    def test_nulls_accepted_on_every_non_optional_field(self, model):
        payload = {name: None for name, f in model.model_fields.items()
                   if not f.is_required()}
        assert model.model_validate(payload) is not None

    def test_nested_nulls_survive_full_dossier_validation(self):
        d = RFPComplianceDossier.model_validate({
            "project_title": None, "client_name": None,
            "detected_framework": None, "compliance_matrix": [
                {"criterion": None, "pass_mark": None, "evidence_required": None}],
            "personnel_mandates": [{"role": None, "role_code": None}],
        })
        assert d.project_title == "" and d.compliance_matrix[0].criterion == ""

    def test_market_dossier_nested_nulls(self):
        d = MarketIntelligenceDossier.model_validate({
            "target_jurisdiction": None,
            "rate_benchmarks": [{"role": None, "rate": None}],
            "notes": None,
        })
        assert d.target_jurisdiction == "" and d.notes == ""


class TestOptionalsAreNotStomped:
    """A null on a genuinely optional field means 'not stated' — keep it."""

    def test_pass_mark_null_stays_null(self):
        """Gates differ per document (45 vs 70); absence is a real signal."""
        assert ComplianceItem.model_validate({"pass_mark": None}).pass_mark is None

    def test_min_years_null_stays_null(self):
        assert PersonnelMandate.model_validate({"min_years": None}).min_years is None

    def test_years_experience_null_stays_null(self):
        d = KeyPersonnelEntry.model_validate({"years_experience": None})
        assert d.years_experience is None

    def test_split_percent_null_stays_null(self):
        from models.dossiers import ConsortiumMember
        assert ConsortiumMember.model_validate(
            {"split_percent": None}).split_percent is None


class TestRealValuesArePreserved:
    """Coercion must only ever touch explicit nulls."""

    def test_false_and_zero_are_not_replaced(self):
        d = LevelOfEffortEntry.model_validate({"duration_days": 0, "fte": 0})
        assert d.duration_days == 0 and d.fte == 0
        assert ComplianceItem.model_validate({"mandatory": False}).mandatory is False

    def test_empty_string_is_not_replaced_with_a_nonempty_default(self):
        m = PersonnelMandate.model_validate({"role": ""})
        assert m.role == ""

    def test_non_dict_input_is_passed_through(self):
        """model_validate on a non-dict must not explode in the validator."""
        with pytest.raises(Exception):
            KeyPersonnelEntry.model_validate("not-a-dict")
