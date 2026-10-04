"""Tests for deterministic CV extraction.

Every fixture here is **synthetic**. The real sample CVs are personal data and
live outside the repo; nothing in this file reproduces a real person's name,
employer, email or phone number.

Each test below is a bug that was actually observed against real CVs, so the
file doubles as a regression log:

  * IGNORECASE + ``[A-Z]`` — under ``re.IGNORECASE`` the character class also
    matches lowercase, so a "is this an ALL-CAPS heading?" regex matched every
    capitalised name and truncated name search at the first line of a CV.
  * Decorative rules — the extraction harness emits ``===== PAGE 1 =====``;
    treated as an ALL-CAPS heading it stopped the name scan immediately.
  * Merged Word-table cells — a DOCX table row extracts as
    ``"1. | Name of Staff | X | X | X"``, duplicating the value per merged cell.
  * Form labels — ``"Employer: Acme"`` is a label, not a person's name.
  * Prose employers — a duty line containing "solutions" was chosen as an
    employer over the actual company name, because both matched the org pattern.
  * Education ranges — ``2005 - 2007`` under EDUCATION counted as employment
    and inflated experience from 17 years to 29.
  * Concurrent roles — teaching alongside consulting double-counted unless
    intervals are unioned rather than summed.
"""

from __future__ import annotations

import pytest

from parsing.cv import (
    extract_cv,
    extract_cv_file,
    load_document_text,
    find_date_ranges,
    is_org_line,
    is_title_line,
    parse_point,
)

# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("token,year,month", [
    ("2019", 2019, 1),
    ("Sept 2021", 2021, 9),
    ("September 2021", 2021, 9),
    ("Aug 2014", 2014, 8),
    ("03/2019", 2019, 3),
    ("02/2026", 2026, 2),
    ("3/19", 2019, 3),
    ("12/99", 1999, 12),
    ("garbage", None, None),
])
def test_parse_point(token, year, month):
    got = parse_point(token)
    if year is None:
        assert got is None
    else:
        assert got == (year, month)


def test_date_token_never_matches_a_bare_number_in_prose():
    """A salary or a clause count must not register as an employment range."""
    text = "The contract provides for 60 days of notice and a fee of 50000."
    assert find_date_ranges(text) == []


def test_range_may_use_a_dash_or_the_word_to():
    for text in ("2015 – 2018", "2015 - 2018", "2015 to 2018", "2015—2018"):
        assert len(find_date_ranges(f"Engineer\n{text}\nAcme Ltd")) == 1


def test_inverted_range_is_rejected():
    assert find_date_ranges("Engineer\n2018 – 2015\nAcme Ltd") == []


# --------------------------------------------------------------------------- #
# Experience derivation
# --------------------------------------------------------------------------- #


def test_years_are_derived_from_ranges_not_read_from_prose():
    cv = """Ada Lovelace
ada@example.org
EXPERIENCE
Senior Engineer
January 2015 – January 2025
Acme Engineering Ltd
"""
    ext = extract_cv(cv)
    assert ext.years_experience.value == 10.0


def test_overlapping_concurrent_roles_are_unioned_not_summed():
    """Two roles held at once must not double-count.

    Real case: a CV listed teaching 04/2023–10/2023 alongside consulting
    05/2022–01/2026. Summing gave ~27y where the truth is ~22y.
    """
    cv = """Ada Lovelace
EXPERIENCE
Consultant
05/2022 – 01/2026
Acme Consulting Ltd
Teacher
04/2023 – 10/2023
Ridgeway College
"""
    ext = extract_cv(cv)
    # union(2022-05..2026-01) = 44 months = 3.7y, not 3.7 + 0.5
    assert ext.years_experience.value == pytest.approx(3.7, abs=0.1)


def test_education_dates_are_not_counted_as_employment():
    """The 29-vs-17 bug: a degree range inflated a 17-year career to 29."""
    cv = """Ada Lovelace
EXPERIENCE
Senior Engineer
2010 – 2020
Acme Engineering Ltd
EDUCATION
BSc Computer Science
2001 – 2005
Some University
"""
    ext = extract_cv(cv)
    assert ext.years_experience.value == pytest.approx(10.0, abs=0.1)


def test_employment_heading_reopens_the_window():
    """A CV that puts EDUCATION first must still find the roles that follow."""
    cv = """Ada Lovelace
EDUCATION
BSc Computing
2001 – 2005
Some University
EXPERIENCE
Senior Engineer
2010 – 2020
Acme Engineering Ltd
"""
    ext = extract_cv(cv)
    assert ext.years_experience.value == pytest.approx(10.0, abs=0.1)


def test_ongoing_role_counts_to_the_reference_date():
    cv = """Ada Lovelace
EXPERIENCE
Director
02/2024 – Present
Acme Engineering Ltd
"""
    ext = extract_cv(cv)
    assert ext.years_experience.value == pytest.approx(2.7, abs=0.2)


def test_stated_and_derived_years_are_reported_separately():
    cv = """Ada Lovelace
Senior engineer with 20+ years of experience.
EXPERIENCE
Engineer
2015 – 2018
Acme Ltd
"""
    ext = extract_cv(cv)
    assert ext.stated_years.value == 20
    assert ext.years_experience.value == pytest.approx(3.0, abs=0.1)
    assert ext.warnings, "a large gap should warn, not be silently averaged"


def test_implausible_career_span_raises_a_warning():
    cv = """Ada Lovelace
EXPERIENCE
Engineer
1960 – 2020
Acme Ltd
"""
    assert any("plausible" in w for w in extract_cv(cv).warnings)


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #


def test_name_found_below_a_page_marker():
    """Decorative rules must not read as ALL-CAPS headings."""
    cv = "========== PAGE 1 ==========\nAda Lovelace\nada@example.org\n"
    assert extract_cv(cv).full_name.value == "Ada Lovelace"


def test_name_near_the_email_beats_the_first_line():
    cv = "Curriculum Vitae\n\nAda Lovelace\nada@example.org\n"
    assert extract_cv(cv).full_name.value == "Ada Lovelace"


def test_form_label_is_never_a_name():
    """'Employer: UHRS' carries a colon and is a label, not a person."""
    cv = "10. Employment Record\nFrom: Sep 2021 To: Till Date\nEmployer: Synercon Engineering\n"
    assert extract_cv(cv).full_name.value in (None, "")


def test_world_bank_form_name_skips_duplicated_merged_cells():
    cv = "1. | Name of Staff | Ada Lovelace | Ada Lovelace | Ada Lovelace\n"
    assert extract_cv(cv).full_name.value == "Ada Lovelace"


def test_name_line_never_carries_an_org_suffix():
    cv = "Acme Engineering Ltd\nhello@acme.example\n"
    assert not extract_cv(cv).full_name.value


def test_section_heading_is_not_a_name():
    cv = "PROFESSIONAL SUMMARY\nada@example.org\n"
    assert not extract_cv(cv).full_name.value


# --------------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------------- #


def test_email_and_phone_are_extracted_and_emoji_stripped():
    cv = "Ada Lovelace\n📞 +92-345-8901746\n📧 ada@example.org\n"
    ext = extract_cv(cv)
    assert ext.email.value == "ada@example.org"
    assert ext.phone.value == "+92-345-8901746"


def test_phone_with_internal_spaces_is_kept_intact():
    cv = "Ada Lovelace\n+47 942 40 917\nada@example.org\n"
    assert extract_cv(cv).phone.value == "+47 942 40 917"


def test_a_year_is_not_mistaken_for_a_phone_number():
    cv = "Ada Lovelace\nada@example.org\nEXPERIENCE\nEngineer\n2015 – 2018\nAcme Ltd\n"
    assert not extract_cv(cv).phone.value


# --------------------------------------------------------------------------- #
# Employment block binding
# --------------------------------------------------------------------------- #


def test_employer_first_layout():
    cv = """Ada Lovelace
EXPERIENCE
Acme Engineering Ltd
Senior Engineer
01/2015 – 01/2020
"""
    ext = extract_cv(cv)
    role = ext.roles[0]
    assert role["title"] == "Senior Engineer"
    assert role["employer"] == "Acme Engineering Ltd"


def test_title_first_layout_with_employer_after_the_dates():
    """The overseas-CV convention: title, dates, then employer."""
    cv = """Ada Lovelace
PROFESSIONAL EXPERIENCE
Senior Engineer
2015 – 2020
Acme Engineering Ltd — London, UK
"""
    ext = extract_cv(cv)
    role = ext.roles[0]
    assert role["title"] == "Senior Engineer"
    assert role["employer"] == "Acme Engineering Ltd"


def test_location_is_stripped_from_the_employer():
    cv = """Ada Lovelace
EXPERIENCE
Acme Engineering Ltd — Oslo, Norway
Senior Engineer
2015 – 2020
"""
    assert extract_cv(cv).roles[0]["employer"] == "Acme Engineering Ltd"


def test_a_prose_line_is_not_an_employer():
    """'...based solutions to major retail clients' is a duty statement."""
    assert not is_org_line("Delivered multiple successful solutions to retail clients")
    assert is_org_line("Acme Solutions Ltd")
    assert is_org_line("LMK Resources, Islamabad, Pakistan")


def test_page_marker_is_never_a_title_or_employer():
    assert not is_title_line("========== PAGE 2 ==========")
    assert not is_org_line("========== PAGE 2 ==========")


def test_technologies_line_is_never_an_employer():
    cv = """Ada Lovelace
EXPERIENCE
Acme Engineering Ltd
Senior Engineer
2015 – 2020
Technologies: C# · .NET Core · Azure
"""
    assert extract_cv(cv).roles[0]["employer"] == "Acme Engineering Ltd"


# --------------------------------------------------------------------------- #
# World Bank form
# --------------------------------------------------------------------------- #


WB_CV = """Saadat-style World Bank CV form
1. | Name of Staff | Ada Lovelace | Ada Lovelace | Ada Lovelace
2. | Proposed Position | Project Manager | Project Manager | Project Manager
10. Employment Record
From: Sep 2021\t\tTo: Till Date
Employer: Synercon Engineering
Position Held: Director
From: Dec 2018\t\tTo: Sep 2021
Employer: Acme Pvt. Ltd.
Position Held: Engineering Manager
6. | Professional Certification or Membership in Professional Associations: | Professional Engineer, Pakistan Engineering Council
"""


def test_world_bank_genre_is_detected():
    assert extract_cv(WB_CV).genre == "worldbank-form"


def test_world_bank_roles_carry_title_employer_and_ongoing():
    roles = extract_cv(WB_CV).roles
    assert roles[0]["employer"] == "Synercon Engineering"
    assert roles[0]["title"] == "Director"
    assert roles[0]["ongoing"] is True
    assert roles[1]["ongoing"] is False


def test_world_bank_current_role_is_the_ongoing_one():
    assert extract_cv(WB_CV).current_role.value == "Director"


def test_world_bank_employer_is_the_ongoing_one():
    assert extract_cv(WB_CV).employer.value == "Synercon Engineering"


# --------------------------------------------------------------------------- #
# Skills and certifications
# --------------------------------------------------------------------------- #


def test_skills_are_collected_from_headings_and_technology_lines():
    cv = """Ada Lovelace
CORE COMPETENCIES
· Python
· Distributed systems
EXPERIENCE
Engineer
2015 – 2020
Acme Ltd
Technologies: Azure · Terraform · Kafka
"""
    skills = extract_cv(cv).skills.value
    assert "Python" in skills
    assert "Terraform" in skills


def test_certifications_are_deduplicated_and_canonicalised():
    cv = "Ada Lovelace\nPMP, PMI-PMP, ISO 27001, Scrum\n"
    certs = extract_cv(cv).certifications.value
    assert certs.count("PMP") == 1
    assert "ISO 27001" in certs


def test_known_graduation_credential_is_found():
    cv = "Ada Lovelace\nMember: Pakistan Engineering Council\n"
    assert extract_cv(cv).certifications.value


# --------------------------------------------------------------------------- #
# Bench row shape
# --------------------------------------------------------------------------- #


def test_to_bench_produces_the_team_cvs_shape():
    cv = """Ada Lovelace
ada@example.org
EXPERIENCE
Senior Engineer
01/2015 – 01/2020
Acme Engineering Ltd
"""
    row = extract_cv(cv).to_bench(user_id="u-1")
    assert row["user_id"] == "u-1"
    assert row["full_name"] == "Ada Lovelace"
    assert row["current_role"] == "Senior Engineer"
    assert row["years_experience"] == 5
    assert isinstance(row["certifications"], list)
    assert isinstance(row["skills"], list)


def test_to_bench_never_emits_null_for_a_missing_optional_field():
    """A null must not invalidate the insert; empty lists are valid."""
    row = extract_cv("Ada Lovelace\nada@example.org\n").to_bench()
    for value in row.values():
        assert value is not None


def test_empty_input_yields_warnings_not_an_exception():
    ext = extract_cv("")
    assert ext.roles == []
    assert ext.warnings


# --------------------------------------------------------------------------- #
# File loading
# --------------------------------------------------------------------------- #


def test_loads_txt_and_md(tmp_path):
    for name in ("cv.txt", "cv.md"):
        p = tmp_path / name
        p.write_text("Ada Lovelace\nada@example.org\n")
        assert "Ada Lovelace" in load_document_text(p)


def test_loads_a_real_docx_round_trip(tmp_path):
    import docx

    p = tmp_path / "cv.docx"
    doc = docx.Document()
    doc.add_paragraph("Ada Lovelace")
    doc.add_paragraph("ada@example.org")
    doc.save(str(p))

    ext = extract_cv_file(p)
    assert ext.full_name.value == "Ada Lovelace"
    assert ext.email.value == "ada@example.org"


def test_docx_tables_are_read_as_pipe_delimited_rows(tmp_path):
    """World Bank CV forms are Word tables; the rows must survive extraction."""
    import docx

    p = tmp_path / "wb.docx"
    doc = docx.Document()
    t = doc.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "Name of Staff"
    t.rows[0].cells[1].text = "Ada Lovelace"
    doc.save(str(p))

    assert "Name of Staff | Ada Lovelace" in load_document_text(p)


def test_docx_header_text_is_read(tmp_path):
    """A contact block in the page header must not be invisible to the parser."""
    import docx

    p = tmp_path / "hdr.docx"
    doc = docx.Document()
    doc.add_paragraph("EXPERIENCE")
    doc.add_paragraph("Engineer")
    doc.add_paragraph("2015 - 2020")
    doc.add_paragraph("Acme Ltd")
    doc.sections[0].header.paragraphs[0].text = "Ada Lovelace"
    doc.save(str(p))

    text = load_document_text(p)
    assert "Ada Lovelace" in text


def test_unsupported_suffix_is_rejected_loudly(tmp_path):
    p = tmp_path / "cv.rtf"
    p.write_text("Ada Lovelace")
    with pytest.raises(ValueError, match="unsupported CV format"):
        load_document_text(p)


def test_legacy_doc_says_what_to_do(tmp_path):
    p = tmp_path / "cv.doc"
    p.write_bytes(b"\xd0\xcf\x11\xe0 legacy")
    with pytest.raises(ValueError, match="save as .docx"):
        load_document_text(p)


def test_scan_with_no_text_layer_warns_instead_of_failing_silently(tmp_path):
    p = tmp_path / "scan.txt"
    p.write_text("A")                     # simulates an OCR-less scan
    ext = extract_cv_file(p)
    assert any("scan" in w for w in ext.warnings)


def test_a_blank_file_does_not_raise(tmp_path):
    p = tmp_path / "blank.txt"
    p.write_text("")
    assert extract_cv_file(p).roles == []
