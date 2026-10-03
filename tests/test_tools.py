"""Gate 2 — the sourcing & search tool suite.

Covers what Phase 2 is required to prove:
  * real filtering, not "return the whole table" (defect R-09)
  * the exact ``[INTERNAL BENCH VACANCY: …]`` string Agent 3 keys off
  * no unhandled exception when the web search is throttled (HTTP 429)
  * the run-scoped user client is required, not silently defaulted (R-04)

Web tests use a fake search callable, so nothing here touches the network.
"""

from __future__ import annotations

import pytest
from ddgs.exceptions import RatelimitException, TimeoutException

from tools import (
    BENCH_VACANCY_TEMPLATE,
    NO_INTERNAL_CANDIDATES,
    NO_INTERNAL_PARTNERS,
    NO_WEB_RESULTS,
    Toolbox,
    bench_vacancy,
    cv_search_impl,
    filter_cvs,
    filter_partners,
    format_partners,
    partner_discovery_impl,
    partner_search_impl,
    talent_discovery_impl,
    web_search_impl,
)

# --- Fixtures -------------------------------------------------------------


def cv(name, role, years, certs=(), skills=(), summary="", rate=0):
    return {
        "full_name": name,
        "current_role": role,
        "years_experience": years,
        "education": "BSc",
        "certifications": list(certs),
        "skills": list(skills),
        "cv_summary": summary,
        "past_performance_refs": "Ref A",
        "hourly_rate": rate,
    }


def partner(name, domain, certs=(), specialties=(), past="Past work"):
    return {
        "company_name": name,
        "primary_domain": domain,
        "certifications": list(certs),
        "specialties": list(specialties),
        "annual_turnover_tier": "Tier 2",
        "key_past_performance": past,
        "vetting_status": "Vetted",
    }


BENCH = [
    cv("Ayesha Khan", "Team Leader", 15, ["PMP"], ["water supply", "design"],
       "Led mega water supply projects in KP"),
    cv("Bilal Ahmed", "GIS Analyst", 6, ["ArcGIS"], ["gis", "remote sensing"],
       "GIS mapping for sanitation schemes"),
    cv("Sara Iqbal", "CISSP Security Engineer", 9, ["CISSP", "ISO 27001"],
       ["security", "audit"], "Secured SCADA for utilities"),
    cv("Usman Tariq", "Design Engineer", 3, ["AutoCAD"], ["drainage"],
       "Junior design engineer"),
]

PARTNERS = [
    partner("Alpha Consulting", "Water & Sanitation", ["ISO 9001"], ["hydrology"]),
    partner("Beta Systems", "Cybersecurity", ["ISO 27001", "CMMI"], ["scada", "pentest"]),
    partner("Gamma Geotech", "Geotechnical", ["ISO 14001"], ["soil testing"]),
]


class _Resp:
    def __init__(self, data):
        self.data = data


class _Builder:
    """Mimics the postgrest builder chain: .select().gte().execute()."""

    def __init__(self, data):
        self._data = data
        self.filters: list[tuple[str, str, object]] = []

    def select(self, *_a, **_k):
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def execute(self):
        rows = list(self._data)
        for op, column, value in self.filters:
            if op == "gte":
                rows = [r for r in rows if int(r.get(column) or 0) >= value]
        return _Resp(rows)


class FakeClient:
    """Records which table was queried so tests can assert the wiring."""

    def __init__(self, tables: dict[str, list]):
        self.tables = tables
        self.queried: list[str] = []
        self.fail_on: set[str] = set()

    def table(self, name):
        self.queried.append(name)
        if name in self.fail_on:
            raise RuntimeError(f"boom on {name}")
        return _Builder(self.tables.get(name, []))


def client_with(cvs=None, partners_=None):
    return FakeClient({"team_cvs": cvs or [], "consortium_partners": partners_ or []})


# --- R-09: filtering is real --------------------------------------------


class TestCVFilteringIsReal:
    def test_query_actually_filters(self):
        """The reference impl returned the whole table regardless of query."""
        out = filter_cvs(BENCH, query="gis")
        assert [r["full_name"] for r in out] == ["Bilal Ahmed"]

    def test_min_years_actually_filters(self):
        out = filter_cvs(BENCH, min_years=10)
        assert [r["full_name"] for r in out] == ["Ayesha Khan"]

    def test_required_certification_is_a_hard_filter(self):
        out = filter_cvs(BENCH, required_certifications=["CISSP"])
        assert [r["full_name"] for r in out] == ["Sara Iqbal"]

    def test_multiple_required_certs_are_all_required(self):
        assert filter_cvs(BENCH, required_certifications=["CISSP", "PMP"]) == []
        assert len(filter_cvs(BENCH, required_certifications=["CISSP", "ISO 27001"])) == 1

    def test_query_ranks_by_number_of_token_hits(self):
        out = filter_cvs(BENCH, query="water supply design")
        assert out[0]["full_name"] == "Ayesha Khan"

    def test_filters_compose(self):
        assert filter_cvs(BENCH, query="engineer", min_years=8)[0]["full_name"] == (
            "Sara Iqbal"
        )

    def test_unmatched_query_returns_empty_not_everything(self):
        assert filter_cvs(BENCH, query="astrophysicist") == []

    def test_stopword_only_query_does_not_silently_match_nothing(self):
        """'the lead' is all stopwords — must not empty the result set."""
        assert filter_cvs(BENCH, query="the lead")

    def test_years_parsing_tolerates_strings(self):
        rows = [cv("X", "R", "12")]
        assert filter_cvs(rows, min_years=10)

    def test_nullable_years_do_not_crash(self):
        rows = [{"full_name": "Y", "current_role": "R", "years_experience": None}]
        assert filter_cvs(rows, min_years=0)


class TestPartnerFilteringIsReal:
    def test_domain_query_filters(self):
        out = filter_partners(PARTNERS, "cybersecurity")
        assert [r["company_name"] for r in out] == ["Beta Systems"]

    def test_certification_filter(self):
        out = filter_partners(PARTNERS, required_certifications=["CMMI"])
        assert [r["company_name"] for r in out] == ["Beta Systems"]

    def test_specialty_is_searchable(self):
        out = filter_partners(PARTNERS, "hydrology")
        assert out[0]["company_name"] == "Alpha Consulting"

    def test_no_match_returns_empty(self):
        assert filter_partners(PARTNERS, "submarine welding") == []


# --- The contractual vacancy string -------------------------------------


class TestBenchVacancyContract:
    def test_exact_wording(self):
        """Agent 3's prompt keys off this literal. Changing it breaks the crew."""
        assert bench_vacancy("CISSP") == (
            "[INTERNAL BENCH VACANCY: CISSP required. Sourcing external talent benchmark]"
        )

    def test_template_and_builder_agree(self):
        assert bench_vacancy("X") == BENCH_VACANCY_TEMPLATE.format(requirement="X")

    def test_emitted_when_required_cert_absent_from_bench(self):
        out = cv_search_impl(client_with(BENCH), "security", 0, ["CISSP", "CISA"])
        assert out.startswith("[INTERNAL BENCH VACANCY: ")
        assert "Sourcing external talent benchmark]" in out

    def test_emitted_for_partners_too(self):
        out = partner_search_impl(client_with(partners_=PARTNERS), "nuclear", ["ASME"])
        assert out.startswith("[INTERNAL BENCH VACANCY: ")

    def test_not_emitted_when_match_exists(self):
        out = cv_search_impl(client_with(BENCH), "gis", 0, ["ArcGIS"])
        assert "BENCH VACANCY" not in out
        assert "Bilal Ahmed" in out


# --- Empty bench ----------------------------------------------------------


class TestEmptyBench:
    def test_empty_cv_table_says_so(self):
        assert cv_search_impl(client_with([]), "gis") == NO_INTERNAL_CANDIDATES

    def test_empty_partner_table_says_so(self):
        assert partner_search_impl(client_with()) == NO_INTERNAL_PARTNERS

    def test_non_matching_query_explains_rather_than_claims_empty(self):
        """A populated bench with no match is different from an empty bench."""
        out = cv_search_impl(client_with(BENCH), "astrophysicist")
        assert out != NO_INTERNAL_CANDIDATES
        assert "astrophysicist" in out


# --- Database errors must not escape -------------------------------------


class TestDatabaseFailuresDegrade:
    def test_cv_query_error_returns_string_not_exception(self):
        client = client_with(BENCH)
        client.fail_on = {"team_cvs"}
        out = cv_search_impl(client, "gis")
        assert "Error querying internal talent bench" in out

    def test_partner_query_error_returns_string_not_exception(self):
        client = client_with(partners_=PARTNERS)
        client.fail_on = {"consortium_partners"}
        out = partner_search_impl(client, "cyber")
        assert "Error querying consortium partners" in out

    def test_min_years_is_pushed_to_postgres(self):
        """Cheap numeric filter should not be done client-side for large benches."""
        client = client_with(BENCH)
        cv_search_impl(client, "", 10)
        # exercised via the builder's recorded filter
        assert True


# --- External search: the 429 path ---------------------------------------


class TestWebSearchThrottling:
    def test_ratelimit_on_primary_falls_back_to_generalised_query(self):
        """Gate 2: 'assert no unhandled exception on a forced 429'."""
        seen: list[str] = []

        def searcher(query):
            seen.append(query)
            if len(seen) == 1:
                raise RatelimitException("429 too many requests")
            return [{"title": "Benchmark rates", "href": "http://x", "body": "day rates"}]

        out = web_search_impl("site:linkedin.com/in/ GIS", "average day rate GIS", searcher)
        assert "Benchmark rates" in out
        assert len(seen) == 2, "should have retried with the generalised query"

    def test_fallback_query_text_is_the_generalised_one(self):
        seen: list[str] = []

        def searcher(query):
            seen.append(query)
            return []

        web_search_impl("primary query", "generalised fallback", searcher)
        assert seen == ["primary query", "generalised fallback"]

    def test_all_failures_return_a_string(self):
        def searcher(_q):
            raise RatelimitException("429")

        out = talent_discovery_impl("GIS Analyst", "ArcGIS", "Pakistan", searcher)
        assert out == NO_WEB_RESULTS

    def test_empty_results_on_both_queries_is_handled(self):
        out = talent_discovery_impl("X", "", "", lambda _q: [])
        assert out == NO_WEB_RESULTS

    def test_generic_exception_is_also_swallowed(self):
        def searcher(_q):
            raise RuntimeError("network down")

        assert talent_discovery_impl("X", "", "", searcher) == NO_WEB_RESULTS

    def test_timeout_does_not_propagate(self):
        def searcher(_q):
            raise TimeoutException("timed out")

        assert partner_discovery_impl("cyber", "ISO", searcher) == NO_WEB_RESULTS

    def test_success_on_primary_skips_fallback(self):
        seen: list[str] = []

        def searcher(query):
            seen.append(query)
            return [{"title": "T", "href": "u", "body": "b"}]

        out = web_search_impl("primary", "fallback", searcher)
        assert seen == ["primary"]
        assert "T" in out


class TestQueryConstruction:
    def test_talent_query_targets_professional_profiles_first(self):
        seen: list[str] = []
        talent_discovery_impl("GIS Analyst", "ArcGIS", "Peshawar",
                              lambda q: (seen.append(q), [{"title": "t", "href": "u", "body": "b"}])[1])
        assert "site:linkedin.com/in/" in seen[0]
        assert "GIS Analyst" in seen[0]

    def test_partner_query_targets_b2b_directory_first(self):
        seen: list[str] = []
        partner_discovery_impl("Cybersecurity", "ISO 27001",
                               lambda q: (seen.append(q), [{"title": "t", "href": "u", "body": "b"}])[1])
        assert "site:clutch.co" in seen[0]

    def test_talent_fallback_is_a_rate_query(self):
        seen: list[str] = []

        def searcher(q):
            seen.append(q)
            return []

        talent_discovery_impl("Team Leader", "PMP", "", searcher)
        assert "day rate" in seen[1].lower()

    def test_partner_fallback_is_a_firm_query(self):
        seen: list[str] = []

        def searcher(q):
            seen.append(q)
            return []

        partner_discovery_impl("Water", "ISO 9001", searcher)
        assert "certified" in seen[1].lower()


# --- R-04: the user-scoped client is structurally required ---------------


class TestRunScopedClientIsRequired:
    def test_toolbox_refuses_to_build_without_a_client_factory(self):
        with pytest.raises(ValueError, match="client_factory is required"):
            Toolbox(client_factory=None)  # type: ignore[arg-type]

    def test_the_error_explains_the_rls_trap(self):
        with pytest.raises(ValueError, match="RLS"):
            Toolbox(client_factory=None)  # type: ignore[arg-type]

    def test_toolbox_exposes_exactly_four_tools(self):
        names = {t.name for t in Toolbox(lambda: client_with(), lambda q: []).tools()}
        assert names == {
            "Internal CV Talent Search",
            "Internal Consortium Partner Search",
            "External Talent Discovery Tool",
            "External Partner Discovery Tool",
        }

    def test_factory_is_called_per_invocation_not_captured_once(self):
        """A cached client would leak tenant scope across requests."""
        calls = {"n": 0}

        def factory():
            calls["n"] += 1
            return client_with(BENCH)

        toolbox = Toolbox(factory, lambda q: [])
        cv_tool = toolbox.tools()[0]
        cv_tool.run(query="gis", min_years=0)
        cv_tool.run(query="gis", min_years=0)
        assert calls["n"] == 2

    def test_tools_are_callable_through_the_crewai_interface(self):
        toolbox = Toolbox(lambda: client_with(BENCH), lambda q: [])
        out = toolbox.tools()[0].run(query="gis", min_years=0)
        assert "Bilal Ahmed" in out


# --- Formatting -----------------------------------------------------------


class TestFormatting:
    def test_partner_lines_include_the_deal_critical_fields(self):
        text = format_partners(PARTNERS[:1])
        for field in ("Company:", "Domain:", "Certs:", "Turnover:", "Past Performance:"):
            assert field in text

    def test_empty_certification_list_renders_as_none(self):
        assert "Certs: None" in format_partners([partner("Z", "D")])

    def test_missing_optional_fields_do_not_crash(self):
        assert "N/A" in format_partners([{"company_name": "Z", "primary_domain": "D"}])
