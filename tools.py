"""Sourcing & search tool suite (Phase 2).

Four tools: two query the internal Supabase bench, two fall back to public web
search via ``ddgs``. They exist because Agent 3 (Resource & Consortium Planner)
must exhaust the internal bench before proposing external sourcing.

Design decisions worth knowing:

**R-04 — the client factory is required, not defaulted.** An anon-key client
sees zero rows under RLS, which silently looks like "empty bench" and sends the
agent off to the external web for no reason. Requiring the factory makes it
impossible to construct a toolbox that is quietly blind; the caller must supply
a run-scoped user client.

**R-09 — every declared argument is actually used.** The reference
implementation accepted ``query`` / ``min_years`` and ignored both, returning
the whole table. Tool schemas are LLM-visible: advertising an argument that does
nothing makes the model waste calls learning that. The filtering here is real
and unit-tested.

**R-02 — ``ddgs``, not ``DuckDuckGoSearchTool``.** The latter no longer exists
in ``crewai_tools``.

The two fallback strings are contractual: Agent 3's prompt keys off the exact
``[INTERNAL BENCH VACANCY: …]`` marker to decide it must look externally.
Changing that wording breaks the agent, so it is built from a constant and
asserted verbatim in the tests.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Sequence

from crewai.tools import tool

log = logging.getLogger(__name__)

# --- Contractual strings --------------------------------------------------

#: Exact marker Agent 3 keys off to trigger external sourcing. Do not reword.
BENCH_VACANCY_TEMPLATE = (
    "[INTERNAL BENCH VACANCY: {requirement} required. Sourcing external talent benchmark]"
)

NO_INTERNAL_CANDIDATES = (
    "No matching internal candidates found in the company bench."
)
NO_INTERNAL_PARTNERS = (
    "No existing consortium partners found in the internal directory."
)
NO_WEB_RESULTS = (
    "Web search returned no results for either the targeted or the generalised "
    "query. Treat external sourcing as unavailable and proceed on internal data."
)

#: ddgs raises rather than returning empty when throttled; we never let that
#: escape a tool, because an unhandled exception kills the whole crew run.
MAX_RESULTS = 6
SEARCH_TIMEOUT_S = 15

#: Words too common to be useful as match keys in a bench search.
_STOPWORDS = frozenset(
    "the a an and or of for with in on at to from senior junior lead chief "
    "head principal staff manager specialist expert engineer officer".split()
)


def bench_vacancy(requirement: str) -> str:
    """Build the exact vacancy marker for a missing requirement."""
    return BENCH_VACANCY_TEMPLATE.format(requirement=requirement)


# --- Internal bench: filtering helpers ------------------------------------


def _as_lower_set(values: Iterable[Any] | None) -> set[str]:
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def _search_tokens(query: str) -> list[str]:
    """Meaningful lowercase tokens from a free-text query."""
    words = [w.strip(".,;:()[]{}\"'/").lower() for w in (query or "").split()]
    meaningful = [w for w in words if len(w) >= 3 and w not in _STOPWORDS]
    # If the query was all stopwords, fall back to the raw words rather than
    # silently matching nothing.
    return meaningful or [w for w in words if w]


def _cv_haystack(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("full_name") or ""),
        str(record.get("current_role") or ""),
        str(record.get("cv_summary") or ""),
        str(record.get("education") or ""),
        " ".join(str(x) for x in record.get("skills") or []),
        " ".join(str(x) for x in record.get("certifications") or []),
    ]
    return " ".join(parts).lower()


def _cv_match_count(record: dict[str, Any], tokens: Sequence[str]) -> int:
    hay = _cv_haystack(record)
    return sum(1 for t in tokens if t in hay)


def filter_cvs(
    records: Sequence[dict[str, Any]],
    query: str = "",
    min_years: int = 0,
    required_certifications: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply real filtering, best matches first.

    ``min_years`` and ``required_certifications`` are hard filters (a candidate
    either has them or is out). ``query`` is a soft, ranked match: a record
    qualifies if any meaningful token appears, and records are ordered by how
    many tokens hit.
    """
    tokens = _search_tokens(query)
    wanted_certs = _as_lower_set(required_certifications)

    scored: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        try:
            years = int(float(record.get("years_experience") or 0))
        except (TypeError, ValueError):
            years = 0
        if years < min_years:
            continue

        if wanted_certs:
            held = _as_lower_set(record.get("certifications"))
            if not wanted_certs.issubset(held):
                continue

        if tokens:
            hits = _cv_match_count(record, tokens)
            if hits == 0:
                continue
            scored.append((hits, record))
        else:
            scored.append((0, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored]


def filter_partners(
    records: Sequence[dict[str, Any]],
    domain_or_cert: str = "",
    required_certifications: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Match partners on domain, specialties, company name, or certifications."""
    tokens = _search_tokens(domain_or_cert)
    wanted_certs = _as_lower_set(required_certifications)

    scored: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        if wanted_certs:
            held = _as_lower_set(record.get("certifications"))
            if not wanted_certs.issubset(held):
                continue

        if not tokens:
            scored.append((0, record))
            continue

        hay = " ".join(
            [
                str(record.get("company_name") or ""),
                str(record.get("primary_domain") or ""),
                str(record.get("key_past_performance") or ""),
                " ".join(str(x) for x in record.get("specialties") or []),
                " ".join(str(x) for x in record.get("certifications") or []),
            ]
        ).lower()
        hits = sum(1 for t in tokens if t in hay)
        if hits:
            scored.append((hits, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _, record in scored]


# --- Internal bench: formatting -------------------------------------------


def format_cvs(records: Sequence[dict[str, Any]]) -> str:
    lines = []
    for r in records:
        certs = ", ".join(str(c) for c in r.get("certifications") or []) or "None"
        skills = ", ".join(str(x) for x in r.get("skills") or []) or "N/A"
        lines.append(
            f"- Name: {r.get('full_name', 'N/A')} | Role: {r.get('current_role', 'N/A')} | "
            f"Exp: {r.get('years_experience', 0)} yrs | Education: {r.get('education') or 'N/A'} | "
            f"Certs: {certs} | Rate: ${r.get('hourly_rate', 0)}/hr\n"
            f"  Skills: {skills}\n"
            f"  Summary: {r.get('cv_summary') or 'N/A'}\n"
            f"  Past Projects: {r.get('past_performance_refs') or 'N/A'}"
        )
    return "\n".join(lines)


def format_partners(records: Sequence[dict[str, Any]]) -> str:
    lines = []
    for r in records:
        certs = ", ".join(str(c) for c in r.get("certifications") or []) or "None"
        lines.append(
            f"- Company: {r.get('company_name', 'N/A')} | Domain: {r.get('primary_domain', 'N/A')} | "
            f"Certs: {certs} | Turnover: {r.get('annual_turnover_tier') or 'N/A'} | "
            f"Status: {r.get('vetting_status') or 'Vetted'}\n"
            f"  Past Performance: {r.get('key_past_performance') or 'N/A'}"
        )
    return "\n".join(lines)


# --- Internal bench: implementations (pure; client injected) --------------


def cv_search_impl(
    client: Any,
    query: str = "",
    min_years: int = 0,
    required_certifications: Sequence[str] | None = None,
) -> str:
    """Query ``team_cvs`` and return matching bench members, or a vacancy marker."""
    try:
        builder = client.table("team_cvs").select("*")
        if min_years:
            # Push the cheap numeric filter to Postgres; text ranking stays here.
            builder = builder.gte("years_experience", int(min_years))
        response = builder.execute()
    except Exception as exc:  # never let a DB error kill the crew
        log.warning("team_cvs query failed: %s", exc)
        return f"Error querying internal talent bench: {exc}"

    records = list(getattr(response, "data", None) or [])
    if not records:
        return NO_INTERNAL_CANDIDATES

    matched = filter_cvs(records, query, min_years, required_certifications)

    if not matched:
        # The vacancy marker is what sends Agent 3 outward, so it must be exact.
        if required_certifications:
            return bench_vacancy(", ".join(str(c) for c in required_certifications))
        if query:
            return (
                f"No internal candidates matched '{query}'. "
                f"Bench holds {len(records)} member(s) but none had the required profile."
            )
        return NO_INTERNAL_CANDIDATES

    return format_cvs(matched)


def partner_search_impl(
    client: Any,
    domain_or_cert: str = "",
    required_certifications: Sequence[str] | None = None,
) -> str:
    """Query ``consortium_partners`` and return matches, or a vacancy marker."""
    try:
        response = client.table("consortium_partners").select("*").execute()
    except Exception as exc:
        log.warning("consortium_partners query failed: %s", exc)
        return f"Error querying consortium partners: {exc}"

    records = list(getattr(response, "data", None) or [])
    if not records:
        return NO_INTERNAL_PARTNERS

    matched = filter_partners(records, domain_or_cert, required_certifications)

    if not matched:
        certs = ", ".join(str(c) for c in (required_certifications or []))
        requirement = certs or domain_or_cert
        return bench_vacancy(requirement)

    return format_partners(matched)


# --- External web search --------------------------------------------------


def ddg_search(query: str) -> list[dict[str, Any]]:
    """Public web search via ``ddgs`` (R-02: ``DuckDuckGoSearchTool`` is gone)."""
    from ddgs import DDGS

    return DDGS().text(query, max_results=MAX_RESULTS) or []


def format_web_results(results: Sequence[dict[str, Any]]) -> str:
    lines = []
    for r in results:
        title = r.get("title") or "(untitled)"
        url = r.get("href") or r.get("url") or ""
        body = (r.get("body") or r.get("description") or "").strip()
        lines.append(f"- {title}\n  {url}\n  {body}".rstrip())
    return "\n".join(lines)


def web_search_impl(
    primary_query: str,
    fallback_query: str,
    searcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> str:
    """Run the targeted query; on throttle/empty/error, generalise and retry.

    Never raises. An unhandled ``RatelimitException`` would abort the whole crew
    run, so every failure degrades to a usable string instead.
    """
    search = searcher or ddg_search
    for query in (primary_query, fallback_query):
        if not query:
            continue
        try:
            results = search(query)
        except Exception as exc:
            # Includes RatelimitException (HTTP 429) — fall through to the
            # generalised query rather than propagating.
            log.warning("web search failed for %r: %s: %s", query, type(exc).__name__, exc)
            continue

        rendered = format_web_results(results)
        if rendered:
            return rendered

        log.info("web search empty for %r; trying generalised query", query)

    return NO_WEB_RESULTS


def talent_discovery_impl(
    role_title: str,
    required_cert: str = "",
    location: str = "",
    searcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> str:
    cert = f'"{required_cert}"' if required_cert else ""
    primary = f'site:linkedin.com/in/ "{role_title}" {cert} {location}'.strip()
    fallback = (
        f"average day rate salary requirements for {role_title} {required_cert}".strip()
    )
    return web_search_impl(primary, fallback, searcher)


def partner_discovery_impl(
    required_domain: str,
    required_cert: str = "",
    searcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> str:
    cert = f'"{required_cert}"' if required_cert else ""
    primary = f'site:clutch.co "{required_domain}" {cert} IT services partner'.strip()
    fallback = (
        f"top certified IT enterprise consulting firms {required_domain} {required_cert}"
    ).strip()
    return web_search_impl(primary, fallback, searcher)


# --- CrewAI tool bindings -------------------------------------------------


class Toolbox:
    """The four Phase-2 tools, bound to a run-scoped client and searcher.

    ``client_factory`` is required on purpose — see the R-04 note at module top.
    ``searcher`` is injectable so tests can force the 429 path without network.
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        searcher: Callable[[str], list[dict[str, Any]]] | None = None,
    ) -> None:
        if client_factory is None:
            raise ValueError(
                "client_factory is required: pass a run-scoped user client "
                "(get_user_client(access_token)). An anon client sees zero rows "
                "under RLS and silently masquerades as an empty bench."
            )
        self.client_factory = client_factory
        self.searcher = searcher

    def tools(self) -> list[Any]:
        """Fresh CrewAI tool objects. Give each agent its own list."""
        factory = self.client_factory
        searcher = self.searcher

        @tool("Internal CV Talent Search")
        def internal_cv_search(
            query: str,
            min_years: int = 0,
            required_certifications: list[str] | None = None,
        ) -> str:
            """Search the company's internal CV bench in Supabase for people who
            match a role, skill set, minimum experience, and any mandatory
            certifications. Always call this before looking outside the company:
            internal people are already vetted and cost nothing to source. If the
            bench holds nobody with a required certification, the result says so
            explicitly and you must then source that skill externally."""
            return cv_search_impl(factory(), query, min_years, required_certifications)

        @tool("Internal Consortium Partner Search")
        def internal_partner_search(
            domain_or_cert: str,
            required_certifications: list[str] | None = None,
        ) -> str:
            """Search the company's directory of vetted consortium partners and
            subcontractors in Supabase. Use this to satisfy corporate
            requirements a bidder cannot meet alone — ISO 27001, CMMI, annual
            turnover thresholds, or a specialist domain. Always try this before
            searching for partners on the open web."""
            return partner_search_impl(factory(), domain_or_cert, required_certifications)

        @tool("External Talent Discovery Tool")
        def external_talent_discovery(
            role_title: str,
            required_cert: str = "",
            location: str = "",
        ) -> str:
            """Search the public web for external candidates and market rate
            benchmarks for a role. Use this only after the internal bench search
            has reported a vacancy. Searches professional profiles first and
            falls back to general rate/benchmark information if that returns
            nothing."""
            return talent_discovery_impl(role_title, required_cert, location, searcher)

        @tool("External Partner Discovery Tool")
        def external_partner_discovery(
            required_domain: str,
            required_cert: str = "",
        ) -> str:
            """Search the public web for corporate joint-venture or
            subcontractor partners holding a specific certification or working
            in a specific domain. Use this only after the internal partner
            directory has reported a vacancy."""
            return partner_discovery_impl(required_domain, required_cert, searcher)

        return [
            internal_cv_search,
            internal_partner_search,
            external_talent_discovery,
            external_partner_discovery,
        ]


__all__ = [
    "BENCH_VACANCY_TEMPLATE",
    "NO_INTERNAL_CANDIDATES",
    "NO_INTERNAL_PARTNERS",
    "NO_WEB_RESULTS",
    "Toolbox",
    "bench_vacancy",
    "cv_search_impl",
    "ddg_search",
    "filter_cvs",
    "filter_partners",
    "format_cvs",
    "format_partners",
    "format_web_results",
    "partner_discovery_impl",
    "partner_search_impl",
    "talent_discovery_impl",
    "web_search_impl",
]
