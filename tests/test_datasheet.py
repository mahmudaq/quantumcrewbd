"""Tests for the deterministic tender extractor (defect R-11).

The fixtures below reproduce the *structure* of the failing passages — the line
breaks matter more than the words. A pass mark is only findable when
"seventy (70) points" survives on one line, and one false positive was caused
specifically by a line break inside "at\nleast thirty".

The two regressions this file exists to prevent:
  * a pass mark reported as 30 — the contract's "at least thirty (30) days'
    written notice of termination" was matched instead of the real
    "Passing Marks 45" in the evaluation table.
  * a document classified as one donor when it merely *mentions* that donor.
"""
from __future__ import annotations

import pytest

from parsing.datasheet import (
    DataSheetResult,
    PassMarkResult,
    detect_framework,
    find_envelope_scheme,
    find_evaluation_marks,
    find_pass_mark,
    find_required_forms,
    find_selection_method,
    locate_data_sheet,
)

# --- real excerpts --------------------------------------------------------- #

# Data Sheet, para 19.4 (truth: 70)
DOC1_DATASHEET = """
DATA SHEET
Para
Description
2.1
Name of Scheme: "Design-Review and Supervision of Municipal
Infrastructure"
2.2
Method of Selection: Single Stage Two Envelopes
System of Selection: Quality and Cost Based Selection (QCBS)
Additional Guidelines: Standard Bidding Documents for Hiring of Services (Khyber
Pakhtunkhwa Public Procurement Rules 2014)
19.4
The financial proposal of only those firms having technical score equal or more than seventy (70) points in their evaluation of technical proposal shall be opened. The formula for determining the financial
scores is the following: Sf = 100 x Fm / F
Section 3. Technical Proposal - Standard Forms
Form TECH-1. Technical Proposal Submission Form
Form TECH-6. Team Composition and Personnel CVs
"""

# Evaluation table (truth: 45)
DOC3_EVAL_TABLE = """
Evaluation Criteria
Quality and Cost Based Selection (QCBS)
Technical Marks
100
Passing Marks
45
Relevant experience, present and past performance
35
Experience of working with the Federal and/or Provincial Governments in undertaking similar kind of Third Party
Evaluation/Feasibility (Qualitative)(Doc Required)
15
"""

# The boilerplate pattern that produced a false positive.
DOC3_FALSE_POSITIVE = """
In such an occurrence the Procuring Agency shall give at
least thirty (30) days' written notice of termination to the Consultant in case
of failure to remedy the same within forty-five (45) days (or such longer period
as the Consultant may have subsequently allowed in writing).
"""


# --- pass mark ------------------------------------------------------------- #

class TestFindPassMark:
    def test_doc1_spelled_with_digits_in_data_sheet(self):
        """'equal or more than seventy (70) points' -> 70."""
        r = find_pass_mark(DOC1_DATASHEET)
        assert r is not None
        assert r.mark == 70
        assert "seventy (70)" in r.evidence
        assert r.strategy == "spelled_with_digits"

    def test_doc3_passing_marks_table(self):
        """The 'Passing Marks\\n45' table row -> 45."""
        r = find_pass_mark(DOC3_EVAL_TABLE)
        assert r is not None
        assert r.mark == 45
        assert r.strategy == "passing_marks_table"

    def test_notice_period_is_not_a_pass_mark(self):
        """REGRESSION: 'at least thirty (30) days written notice' must not match.

        This text makes an extractor report a passing mark of 30 while the
        real answer (45) sits in the evaluation table.
        """
        assert find_pass_mark(DOC3_FALSE_POSITIVE) is None

    def test_does_not_invent_a_mark_when_absent(self):
        """A form-based donor document has no pass mark -> None, never a default."""
        text = ("World Bank Standard Procurement Document. Two-stage Request for "
                "Proposals. The Borrower shall evaluate proposals in accordance "
                "with the criteria in the Data Sheet. Form TECH-1 is required.")
        assert find_pass_mark(text) is None

    def test_data_sheet_scope_preferred_over_body(self):
        """The Data Sheet outranks the body: a decoy in the body must not win."""
        body = ("Somewhere else: minimum technical score of 55 shall apply to "
                "unrelated selection procedures described later.\n")
        r = find_pass_mark(body + DOC1_DATASHEET, data_sheet=locate_data_sheet(DOC1_DATASHEET))
        assert r is not None and r.mark == 70, "body decoy beat the Data Sheet"

    def test_bare_number_without_score_wording_ignored(self):
        assert find_pass_mark("The evaluation contains 70 items in total.") is None

    def test_out_of_range_rejected(self):
        """A 'pass mark' of 3 or 200 is not a percentage threshold."""
        assert find_pass_mark("Passing Marks 200") is None
        assert find_pass_mark("Passing Marks 3") is None

    def test_evidence_is_returned_for_audit(self):
        r = find_pass_mark(DOC3_EVAL_TABLE)
        assert r is not None and r.evidence and "45" in r.evidence

    def test_percent_sign_accepted(self):
        r = find_pass_mark("The minimum technical score is seventy (70) %")
        assert r is not None and r.mark == 70

    @pytest.mark.parametrize("text", ["", "   ", "\n\n"])
    def test_empty_input(self, text):
        assert find_pass_mark(text) is None


# --- data sheet ------------------------------------------------------------ #

class TestLocateDataSheet:
    def test_finds_data_sheet_heading(self):
        ds = locate_data_sheet(DOC1_DATASHEET)
        assert ds is not None
        assert ds.start == DOC1_DATASHEET.index("DATA SHEET")
        assert "seventy (70)" in ds.text

    def test_none_when_absent(self):
        assert locate_data_sheet("Just a short letter with no sheet.") is None

    def test_ignores_stray_mention(self):
        """A passing reference shorter than the minimum is not a section."""
        assert locate_data_sheet("see Data Sheet") is None

    def test_alias_heading(self):
        ds = locate_data_sheet("Instructions to Consultants - Data Sheet\n" + "x " * 60)
        assert ds is not None

    def test_returns_none_on_empty(self):
        assert locate_data_sheet("") is None

    def test_result_is_falsy_when_blank(self):
        assert not DataSheetResult(text="  ", start=0, end=0, heading="")


# --- selection method / envelope ------------------------------------------- #

class TestSelectionMethod:
    @pytest.mark.parametrize("text,expected", [
        ("System of Selection: Quality and Cost Based Selection (QCBS)", "QCBS"),
        ("Quality-Based Selection (QBS) applies", "QBS"),
        ("Selection Based on Consultant's Qualifications", "CQS"),
        ("Least Cost Selection", "LCS"),
        ("Fixed Budget Selection", "FBS"),
        ("Single Source Selection", "SSS"),
    ])
    def test_methods(self, text, expected):
        assert find_selection_method(text) == expected

    def test_none_when_unspecified(self):
        assert find_selection_method("No method named here.") is None


class TestEnvelopeScheme:
    @pytest.mark.parametrize("text,expected", [
        ("Method of Selection: Single Stage Two Envelopes", "Two-Envelope"),
        ("Single-Stage One-Envelope procedure", "One-Envelope"),
        ("one envelope only", "One-Envelope"),
        ("submitted in two envelopes", "Two-Envelope"),
    ])
    def test_envelopes(self, text, expected):
        assert find_envelope_scheme(text) == expected

    def test_none(self):
        assert find_envelope_scheme("nothing about envelopes") is None


# --- forms ----------------------------------------------------------------- #

class TestRequiredForms:
    def test_only_forms_actually_cited(self):
        """A tender that cites no TECH codes must not be given a default set.

        Anchoring a CV engine on TECH-6 when the tender never cites it is how a
        bid gets disqualified for submitting the wrong form set.
        """
        assert find_required_forms("Appendix A through Appendix E apply.") == []

    def test_sorted_numerically_not_lexically(self):
        forms = find_required_forms("Form TECH-10 and Form TECH-2 and Form FIN-1")
        assert forms == ["TECH-2", "TECH-10", "FIN-1"]

    def test_deduplicated(self):
        assert find_required_forms("Form TECH-6 ... Form TECH-6") == ["TECH-6"]


# --- framework detection --------------------------------------------------- #

class TestDetectFramework:
    def test_doc4_world_bank_not_adb(self):
        """REGRESSION: a WB SPD that mentions ADB must not classify as ADB."""
        text = (("World Bank Standard Procurement Document. All references to the "
                 "Bank mean the World Bank. The Asian Development Bank is named "
                 "once as an alternative lender. Form TECH-1 and Form FIN-1 apply.")
                + "World Bank. " * 5)
        out = detect_framework(text)
        assert out["framework"] == "World Bank SPD", out
        assert out["confidence"] == "high"

    def test_adb_dominant(self):
        text = ("Asian Development Bank. " * 5) + "Form TECH-1 Form FIN-1"
        assert detect_framework(text)["framework"] == "ADB QCBS"

    def test_ppra_sbd(self):
        text = ("Standard Bidding Documents for Hiring of Services (Khyber "
                "Pakhtunkhwa Public Procurement Rules 2014)")
        assert detect_framework(text)["framework"] == "PPRA SBD"

    def test_commercial_fallback(self):
        out = detect_framework("A plain commercial contract with no forms.")
        assert out["framework"] == "Custom Commercial"
        assert out["confidence"] == "low"

    def test_signals_are_reported(self):
        out = detect_framework(DOC1_DATASHEET)
        assert isinstance(out["signals"], list) and out["signals"]

    def test_empty(self):
        assert detect_framework("")["framework"] == "Unknown"


# --- evaluation marks ------------------------------------------------------ #

class TestEvaluationMarks:
    def test_technical_and_passing(self):
        out = find_evaluation_marks(DOC3_EVAL_TABLE)
        assert out["technical"] == 100
        assert out["passing"] == 45

    def test_omits_absent_keys(self):
        out = find_evaluation_marks("nothing here")
        assert "passing" not in out and "technical" not in out
