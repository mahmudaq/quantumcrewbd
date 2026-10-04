"""Deterministic CV extraction for the internal bench.

Why this module exists
----------------------
The bench (``team_cvs``) is what the resource planner searches to answer "do we
already have someone who fits this requirement?". Filling it by hand — six text
boxes per person — does not survive a real proposal deadline.

Design stance: extraction is deterministic, not an LLM call.
  * A name, an email address and a date range have one right answer. Asking a
    model to "read" them adds latency, cost and a rate limit to a task a pattern
    already solves.
  * Bench ingestion therefore works with **no network at all**, which matters
    when the demo is a live tender and venue wifi is not guaranteed.
  * Every field records the text that produced it, so a wrong value is
    diagnosable rather than mysterious.

Three document genres appear in practice and they do not parse alike:

  1. **World Bank Standard CV Form** — fixed numbered labels (``Name of Staff``,
     ``Employer:``, ``Position Held:``). Label-driven; highest confidence.
  2. **Narrative, employer-first** — ``Employer \\n Title \\n MM/YYYY – MM/YYYY``
  3. **Narrative, title-first** — ``Title \\n Dates \\n Employer — Location``

No single heuristic reads all three, so strategies run in order and each
extracted field records which one fired.

What this module deliberately does NOT do
-----------------------------------------
It does not produce a prose ``cv_summary``. Summarising is a judgement call, and
a fabricated summary inside a bid document is a liability. Fields here are the
ones with a verifiable answer; the caller supplies any summary.

Experience is *derived, not stated*. Almost no CV says "12 years"; it says
``2013 – 2026``. Where a CV does state a figure ("20+ years"), that number is
returned separately as ``stated_years`` so the two can be compared — a large gap
usually means the CV lists education or a gap the ranges do not capture.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

_MONTHS: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_ALT = "|".join(_MONTHS)
_DATE_ATOM = (
    rf"(?:{_MONTH_ALT})[a-z]*\.?\s*,?\s*\d{{4}}"       # Month YYYY / Sept 2021
    rf"|(?:0?[1-9]|1[0-2])/\d{{4}}"                     # MM/YYYY
    rf"|(?:0?[1-9]|1[0-2])/\d{{2}}(?!\d)"               # MM/YY
    rf"|\d{{4}}"                                         # YYYY
)
_PRESENT = r"(?:present|current|till\s+date|to\s+date|now|ongoing)"
_SEP = r"(?:\s*(?:–|—|―|--|-|to|through|until)\s*)"

_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_ATOM}){_SEP}(?P<end>{_DATE_ATOM}|{_PRESENT})", re.IGNORECASE
)
_WB_RANGE_RE = re.compile(
    rf"from\s*:?\s*(?P<start>{_DATE_ATOM})\s*to\s*:?\s*(?P<end>{_DATE_ATOM}|{_PRESENT})",
    re.IGNORECASE,
)
_STATED_YEARS_RES = (
    re.compile(r"(?P<n>\d{1,2})\s*\+?\s*years?(?:\s+of)?\s+(?:relevant\s+|professional\s+|industry\s+)?(?:experience|work)", re.IGNORECASE),
    re.compile(r"(?:over|more than|exceeding|nearly)\s+(?P<n>\d{1,2})\s*\+?\s*years", re.IGNORECASE),
)

_NOW: tuple[int, int] = (2026, 10)   # deployment reference point; injected in tests


def parse_point(token: str) -> tuple[int, int] | None:
    """Parse a date token to ``(year, month)``; month defaults to January."""
    t = re.sub(r"\s+", " ", str(token).strip().lower().rstrip(".").replace(",", " "))
    if not t:
        return None
    if re.fullmatch(r"\d{4}", t):
        return int(t), 1
    m = re.fullmatch(r"(\d{1,2})/(\d{2,4})", t)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if year < 100:
            year += 2000 if year < 50 else 1900
        return (year, month) if 1 <= month <= 12 else None
    m = re.match(rf"({_MONTH_ALT})[a-z]*\s+(\d{{4}})", t)
    if m:
        return int(m.group(2)), _MONTHS[m.group(1)]
    return None


def _index(point: tuple[int, int]) -> int:
    return point[0] * 12 + (point[1] - 1)


def _merge(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping intervals so concurrent roles are counted once."""
    if not intervals:
        return []
    iv = sorted(intervals)
    out: list[tuple[int, int]] = [iv[0]]
    for s, e in iv[1:]:
        ls, le = out[-1]
        if s <= le:                       # overlapping or touching
            out[-1] = (ls, max(le, e))
        else:
            out.append((s, e))
    return out


@dataclass
class DateRange:
    """A located employment interval plus the text that proves it."""

    start: tuple[int, int]
    end: tuple[int, int] | None          # None = ongoing at time of writing
    raw: str

    @property
    def ongoing(self) -> bool:
        return self.end is None


# --------------------------------------------------------------------------- #
# Line classification
# --------------------------------------------------------------------------- #

_ORG_SUFFIX = re.compile(
    r"\b(Ltd|Limited|LLC|Inc|Incorporated|Corp|Corporation|Company|Co|GmbH|S\.A|AS|AB|"
    r"Pvt|Private|PLC|LLP|Group|Holdings|Technologies|Technology|Solutions|Systems|Services|"
    r"Consultants|Consulting|Engineering|Enterprises|Industries|Networks|Software|Labs|"
    r"University|Universit|Institute|College|School|Academy|Authority|Department|Ministry|"
    r"Agency|Bureau|Commission|Board|Council|Bank|Foundation|Trust|Hospital|Centre|Center|"
    r"Directorate|Programme|Program|Fund|Organization|Organisation|Association|Society|"
    r"Resources|Ventures|Partners|Associates|Enterprises|Works|Studios)\b",
    re.IGNORECASE,
)
_ROLE_WORDS = re.compile(
    r"\b(Engineer|Manager|Director|Developer|Consultant|Analyst|Architect|Lead|Leader|Head|"
    r"Chief|Officer|Specialist|Coordinator|Administrator|Supervisor|Assistant|Associate|"
    r"Executive|Advisor|Adviser|Scientist|Professor|Lecturer|Teacher|Instructor|Trainer|"
    r"Technician|Technologist|Programmer|Designer|Planner|Accountant|Auditor|Inspector|"
    r"Intern|Trainee|Fellow|Researcher|CTO|CEO|CFO|COO|President|Partner|Founder|"
    r"Principal|Senior|Junior|Deputy|SAFe)\b",
    re.IGNORECASE,
)
_DATEISH = re.compile(rf"^\s*(?:{_DATE_ATOM})\b.*(?:{_DATE_ATOM}|{_PRESENT})\s*[,.]?\s*$",
                      re.IGNORECASE)
_SECTION_KEYWORDS = re.compile(
    r"^(?:Professional|Work|Employment|Career|Education|Certifications?|Skills?|Summary|"
    r"Profile|Experience|Training|Languages?|References?|Competencies|Achievements|"
    r"Projects|Publications|Interests|Awards|Objective|Personal|Declaration|Appendix|"
    r"Annex|Additional)\b[^\n]{0,60}$",
    re.IGNORECASE,
)
# Sections whose date ranges are NOT employment and must never count as experience.
_NON_WORK_SECTIONS = re.compile(
    r"^(?:Education|Academic|Professional\s+Development|Training|Certifications?|"
    r"Publications|References?|Languages?|Interests|Awards|Declaration)\b",
    re.IGNORECASE,
)
_SKIP_LINE = re.compile(r"^(?:={3,}|-(?:-{2,})|page\s+\d+|technologies\s*:)", re.IGNORECASE)


def _is_section_heading(s: str) -> bool:
    """True for ALL-CAPS headings and for known section keywords.

    Deliberately not a single IGNORECASE regex: under IGNORECASE, ``[A-Z]`` also
    matches lowercase, so ``^[A-Z][A-Z &/,'()-]{3,}$`` matched "Mahmud Akhtar
    Qureshi" and every other capitalised name — which silently truncated name
    search at the first line of the first CV.
    """
    t = s.strip()
    if not t:
        return False
    if re.search(r"[=\u2500\u2501]{3,}|[\-_]{4,}", t):
        return False                  # decorative rule, not a heading
    if _SECTION_KEYWORDS.match(t):
        return True
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and t == t.upper() and len(t) >= 5


def _norm_org(s: str) -> str:
    """Drop a trailing location from an employer line.

    "Qadir Enterprises, Peshawar, KPK, Pakistan" -> "Qadir Enterprises"
    "Gjensidige Mobility Group AS — Oslo, Norway" -> "Gjensidige Mobility Group AS"
    """
    s = _clean(s)
    s = re.split(r"\s+[—–]\s+", s)[0]              # em/en dash separates location
    parts = [p.strip() for p in s.split(",")]
    if len(parts) > 1 and _ORG_SUFFIX.search(parts[0]):
        return parts[0]
    return s.strip(" -–—|·,")
_BULLET = re.compile(r"^[\s]*[•·▪◦‣∙\-\*\u2022\u25cf\u25aa\u2023]\s*")
_CERT_TOKENS = re.compile(
    r"\b(PMP|PMI-?PMP|PMI|PRINCE2|ITIL|CISSP|CISA|CISM|CRISC|CEH|CCNA|CCNP|CCIE|"
    r"MCSE|MCSA|AWS\s+Certified|Azure\s+Certified|AZ-\d{3}|AI-\d{3}|SC-\d{3}|"
    r"ISO\s*27001|ISO\s*9001|Six\s+Sigma|Lean|CFA|CPA|ACCA|CIMA|CIPD|SCRUM|PSM|CSM|SAFe|"
    r"TOGAF|SHRM|NEBOSH|OSHA|Google\s+Cloud|"
    r"Professional\s+Engineer|Registered\s+Engineer|Chartered\s+\w+|"
    r"(?:Pakistan|PEC)\s+Engineering\s+Council)",
    re.IGNORECASE,
)
_SKILL_HEADING = re.compile(
    r"^(?:core\s+competencies|technical\s+skills|key\s+skills|skills(?:\s*(?:&|and)\s*"
    r"(?:expertise|competencies))?|areas?\s+of\s+expertise|expertise|competencies|"
    r"technologies|tech\s+stack|tools?\s*(?:&|and)\s+technologies)\s*:?\s*$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?)?\d{2,4}(?:[\s.\-]?\d{2,4}){1,3}"
)
_PHONE_SHAPE = re.compile(r"^\+?[\d\s().\-]{9,22}$")
_WB_NAME_RE = re.compile(r"name\s+of\s+staff\s*[:]?\s*(.+)", re.IGNORECASE)
_NAME_STOP = re.compile(
    r"(curriculum\s+vitae|resume|résumé|profile|personal\s+details|contact|"
    r"professional\s+summary|summary|objective|address|reference)",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Strip emoji/pictographs that PDF extraction leaves attached to values."""
    return re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", str(text)).strip()


def _lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in text.splitlines()]


def _norm_name(s: str) -> str:
    s = _clean(s)
    s = re.sub(r"\s*\|\s*.*$", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" -–—|·,")


def is_title_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or "@" in s or _DATEISH.match(s):
        return False
    if _is_section_heading(s) or _SKIP_LINE.match(s):
        return False
    if _ORG_SUFFIX.search(s) and not _ROLE_WORDS.search(s):
        return False
    return bool(_ROLE_WORDS.search(s))


# CV bullets and duty statements start with a verb; an employer name never does.
_ACTION_VERB = re.compile(
    r"^(?:Delivered|Developed|Managed|Led|Built|Contributed|Implemented|Provided|"
    r"Worked|Started|Performed|Conducted|Analyzed|Analysed|Created|Designed|"
    r"Maintained|Supported|Extended|Assisted|Collaborated|Coordinated|Ensured|"
    r"Oversaw|Prepared|Reviewed|Recruited|Trained|Mentored|Supervised|Facilitated|"
    r"Architected|Integrated|Migrated|Optimized|Optimised|Achieved|Responsible|"
    r"Involved|Handled|Gained|Communicated|Introduced|Utilized|Utilised|"
    r"Project|Iterative|Stakeholder|Multidisciplinary|Deliverable|Contractual|"
    r"Risk|Payment|Name|Year|Location|Client|Position|Activities)\b",
    re.IGNORECASE,
)


def is_org_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 110 or "@" in s or _DATEISH.match(s):
        return False
    if _is_section_heading(s) or _SKIP_LINE.match(s) or _BULLET.match(s):
        return False
    # A company name is short. Long lines are prose that merely happens to
    # contain a company-ish word ("...based solutions to major retail clients").
    if len(s.split()) > 9 or _ACTION_VERB.match(s):
        return False
    if _ROLE_WORDS.search(s) and not _ORG_SUFFIX.search(s):
        return False
    return bool(_ORG_SUFFIX.search(s))


def _looks_like_name(s: str) -> bool:
    # "Employer: UHRS" is a form label; a personal name never carries a colon.
    if not s or "@" in s or ":" in s or any(ch.isdigit() for ch in s):
        return False
    if _is_section_heading(s):
        return False
    words = s.split()
    if not (2 <= len(words) <= 5):
        return False
    if _NAME_STOP.search(s) or _ORG_SUFFIX.search(s) or _ROLE_WORDS.search(s):
        return False
    return all(w[0].isupper() for w in words if w[0].isalpha())


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #


@dataclass
class Field:
    """One extracted value plus the evidence and strategy that produced it."""

    value: object
    evidence: str = ""
    strategy: str = ""

    def __bool__(self) -> bool:
        return bool(self.value)


@dataclass
class CVExtraction:
    full_name: Field
    current_role: Field
    years_experience: Field
    certifications: Field
    skills: Field
    email: Field
    phone: Field
    employer: Field
    education: Field
    roles: list[dict] = field(default_factory=list)
    stated_years: Field = field(default_factory=lambda: Field(None))
    warnings: list[str] = field(default_factory=list)
    genre: str = "unknown"

    def to_bench(self, *, user_id: str | None = None) -> dict:
        """Shape for ``team_cvs``. Empty optional fields are omitted, not nulled."""
        row: dict = {
            "full_name": self.full_name.value or "",
            "current_role": self.current_role.value or "",
            "years_experience": int(self.years_experience.value or 0),  # type: ignore[arg-type]
            "certifications": list(self.certifications.value or []),    # type: ignore[arg-type]
            "skills": list(self.skills.value or []),                    # type: ignore[arg-type]
        }
        if user_id:
            row["user_id"] = user_id
        return row


# --------------------------------------------------------------------------- #
# Field extractors
# --------------------------------------------------------------------------- #


def _extract_email(text: str) -> Field:
    m = _EMAIL_RE.search(text)
    return Field(m.group(0).rstrip(".,;"), m.group(0), "regex:email") if m else Field(None)


def _extract_phone(text: str) -> Field:
    for m in _PHONE_RE.finditer(_clean(text)):
        cand = _BULLET.sub("", m.group(0)).strip(" .-|")
        if _PHONE_SHAPE.match(cand) and sum(c.isdigit() for c in cand) >= 9:
            return Field(re.sub(r"\s+", " ", cand), cand, "regex:phone")
    return Field(None)


def _work_sections(text: str) -> list[tuple[str, bool]]:
    """Tag each line as (line, is_employment_section).

    Without this, education dates ("2005 - 2007") and training dates look exactly
    like employment and inflate the derived experience figure.
    """
    tagged: list[tuple[str, bool]] = []
    working = True
    for raw in _lines(text):
        s = raw.strip()
        if _is_section_heading(s):
            working = not _NON_WORK_SECTIONS.match(s)
            if re.match(r"^(?:Work|Employment|Professional)\b", s, re.IGNORECASE):
                working = True          # an employment heading re-opens the window
        tagged.append((s, working))
    return tagged


def find_date_ranges(text: str) -> list[DateRange]:
    """Locate every employment interval, WB-form and inline alike."""
    out: list[DateRange] = []
    seen: set[str] = set()
    work_text = "\n".join(ln for ln, is_work in _work_sections(text) if is_work)
    for rx in (_WB_RANGE_RE, _RANGE_RE):
        for m in rx.finditer(work_text):
            raw = re.sub(r"\s+", " ", m.group(0)).strip()
            if raw.lower() in seen:
                continue
            start = parse_point(m.group("start"))
            end_tok = m.group("end").strip()
            end = None if re.fullmatch(_PRESENT, end_tok, re.IGNORECASE) else parse_point(end_tok)
            if not start:
                continue
            if end and _index(end) < _index(start):     # reversed or bogus
                continue
            seen.add(raw.lower())
            out.append(DateRange(start, end, raw))
    return out


def _years_from_ranges(ranges: list[DateRange]) -> Field:
    """Professional experience = span of the union of employment intervals.

    Union, not sum: overlapping and concurrent roles are common (teaching
    alongside consulting) and summing double-counts them.
    """
    if not ranges:
        return Field(None, "", "none")
    spans = [(_index(r.start), _index(r.end or _NOW)) for r in ranges]
    total_months = sum(e - s for s, e in _merge(spans))
    years = round(total_months / 12, 1)
    earliest = min(r.start for r in ranges)
    return Field(years,
                 f"union of {len(ranges)} interval(s); earliest start {earliest[0]}",
                 "derived:interval-union")


def _stated_years(text: str) -> Field:
    for rx in _STATED_YEARS_RES:
        m = rx.search(text)
        if m:
            return Field(int(m.group("n")), re.sub(r"\s+", " ", m.group(0)), "stated:prose")
    return Field(None)


def _extract_name(text: str, email: str | None) -> Field:
    """Three strategies, most explicit first."""
    m = _WB_NAME_RE.search(text)
    if m:
        # A DOCX table row extracts as "1. | Name of Staff | X | X | X" because
        # merged cells repeat. The name is the first non-empty cell after the label.
        cells = [c.strip() for c in m.group(1).split("|")]
        cand = _norm_name(next((c for c in cells if c), ""))
        if _looks_like_name(cand):
            return Field(cand, re.sub(r"\s+", " ", m.group(0))[:80], "wb:name-of-staff")

    lines = _lines(text)
    if email:                                   # near the email: the header block
        for i, ln in enumerate(lines[:60]):
            if email in ln:
                for j in range(max(0, i - 6), i):
                    cand = _norm_name(lines[j])
                    if _looks_like_name(cand):
                        return Field(cand, lines[j].strip()[:80], "proximity:email")
    for ln in lines[:25]:                       # first plausible line above the fold
        s = ln.strip()
        if _is_section_heading(s):
            break
        cand = _norm_name(s)
        if _looks_like_name(cand):
            return Field(cand, s[:80], "position:header")
    return Field(None)


def _extract_roles_wb(text: str) -> list[dict]:
    """World Bank CV form: ``From: X To: Y`` / ``Employer:`` / ``Position Held:``."""
    roles: list[dict] = []
    cur: dict | None = None
    for raw in _lines(text):
        line = raw.strip()
        if not line:
            continue
        m = re.match(rf"from\s*:?\s*({_DATE_ATOM})\s*(?:to\s*:?\s*)?({_DATE_ATOM}|{_PRESENT})?",
                     line, re.IGNORECASE)
        if m:
            end_tok = (m.group(2) or "").strip()
            cur = {"start": m.group(1), "end": end_tok, "employer": "", "title": "",
                   "ongoing": bool(re.fullmatch(_PRESENT, end_tok, re.IGNORECASE))}
            roles.append(cur)
            continue
        m = re.match(r"employer\s*:\s*(.+)", line, re.IGNORECASE)
        if m and cur is not None:
            cur["employer"] = _norm_org(m.group(1))
            continue
        m = re.match(r"position\s+held\s*:\s*(.+)", line, re.IGNORECASE)
        if m and cur is not None:
            cur["title"] = _norm_name(m.group(1))
    # Drop rows that acquired neither a title nor an employer: those are the
    # "Year: 6 Weeks" assignment-table entries, not employment history.
    return [r for r in roles if r.get("title") or r.get("employer")]


def _extract_roles_narrative(text: str) -> list[dict]:
    """A date line binds to the nearest title and employer beside it.

    Handles both orders, because CVs use both:
        Employer \\n Title \\n MM/YYYY – MM/YYYY      (employer-first)
        Title \\n Dates \\n Employer — City           (title-first)
    """
    tagged = _work_sections(text)
    lines = [ln for ln, _ in tagged]
    work = [w for _, w in tagged]
    roles: list[dict] = []
    for i, ln in enumerate(lines):
        if not work[i]:
            continue
        if not _DATEISH.match(ln.strip()):
            continue
        m = _RANGE_RE.search(ln)
        if not m or not parse_point(m.group("start")):
            continue
        end_tok = m.group("end").strip()
        ongoing = bool(re.fullmatch(_PRESENT, end_tok, re.IGNORECASE))
        prev = [lines[j].strip() for j in range(max(0, i - 4), i)][::-1]   # nearest first
        nxt = [lines[j].strip() for j in range(i + 1, min(len(lines), i + 3))]
        # A title-first CV puts the title immediately above the dates; an
        # employer-first CV puts the title two lines up. Check nearest first.
        title = next((w for w in prev if w and is_title_line(w)), "")
        if not title:
            title = next((w for w in nxt if w and is_title_line(w)), "")

        def _usable(w: str) -> bool:
            # An employer is a proper noun: it starts capitalised and is not a
            # sentence fragment ("field deployment.").
            return bool(w) and w != title and len(w) > 2 \
                and w[0].isupper() and not w.rstrip().endswith(".") \
                and not is_title_line(w) and not _DATEISH.match(w) \
                and not _SKIP_LINE.match(w) and not _is_section_heading(w) \
                and not _BULLET.match(w)

        # An organisation-shaped line is the strongest signal; otherwise the
        # employer is whatever bound the block (it may be above or below).
        employer = next((w for w in prev + nxt if _usable(w) and is_org_line(w)), "")
        if not employer:
            employer = next((w for w in prev + nxt if _usable(w)), "")
        if not title and not employer:
            continue
        roles.append({
            "start": m.group("start").strip(), "end": end_tok,
            "title": _norm_name(title), "employer": _norm_org(employer),
            "ongoing": ongoing,
        })
    return roles


def _extract_employer(text: str, roles: list[dict]) -> Field:
    """Current/most recent substantive employer.

    Preference order:
      1. the employer of an ongoing role - that is genuinely "now"
      2. the registered entity named in the header (World Bank forms put
         ``Employer`` in a table that extracts out of order)
      3. the newest role that has an end date
    """
    for r in roles:
        if r.get("ongoing") and r.get("employer"):
            return Field(r["employer"], r["employer"], "role:ongoing")
    header = re.search(
        r"^\s*([A-Z][^\n,:]{2,60}?)\s*,?\s*(?:Pvt|Private|Ltd|Limited|LLC|Inc)\b",
        text, re.MULTILINE)
    if header:
        return Field(_norm_org(header.group(0)), header.group(0).strip()[:80],
                     "header:registered-entity")
    if roles:
        substantive = [r for r in roles if not r.get("ongoing")] or roles
        for r in substantive:
            if r.get("employer"):
                return Field(r["employer"], r["employer"], "role:recent-substantive")
    owned = re.search(
        r"(?:^|\n)\s*([A-Z][^\n]{2,60}?)\s*,?\s*(?:Pvt|Private|Ltd|Limited|LLC|Inc)\b",
        text, re.MULTILINE)
    if owned:
        return Field(_norm_name(owned.group(1)), owned.group(0).strip()[:80],
                     "entity:registered-name")
    return Field(None)


def _extract_current_role(text: str, roles: list[dict], full_name: str) -> Field:
    for r in roles:
        if r.get("ongoing") and r.get("title"):
            return Field(r["title"], r["title"], "role:ongoing")
    if roles and roles[0].get("title"):
        return Field(roles[0]["title"], roles[0]["title"], "role:most-recent")
    lines = _lines(text)
    # "Name | Senior Software Engineer · ..." — the tail states the role outright,
    # so it outranks any header scan.
    for ln in lines[:12]:
        if full_name and full_name in ln and "|" in ln:
            tail = _clean(ln.split("|", 1)[1])
            if is_title_line(tail):
                return Field(_norm_name(tail), ln.strip()[:80], "header:disambiguator")
    for ln in lines[:8]:
        if is_title_line(ln) and not _ORG_SUFFIX.search(ln):
            return Field(_norm_name(ln), ln.strip()[:80], "position:header")
    return Field(None)


def _extract_education(text: str) -> Field:
    """Highest degree mentioned — ranked, because CVs list several."""
    ranked = [
        (r"\bPh\.?\s?D\b|\bDoctorate\b", "PhD"),
        (r"\bM\.?\s?S(?:c)?\b|\bMaster'?s?\b|\bMBA\b|\bMSc\b|\bM\.?Phil\b", "Master's"),
        (r"\bB\.?\s?S(?:c)?\b|\bBachelor'?s?\b|\bBSc\b|\bB\.?E\.?\b|Bachelors|\bBE\b", "Bachelor's"),
        (r"\bDiploma\b", "Diploma"),
    ]
    for rx, label in ranked:
        m = re.search(rx, text, re.IGNORECASE)
        if m:
            return Field(label, m.group(0), "ranked:highest-degree")
    return Field(None)


def _extract_certifications(text: str) -> Field:
    hits: list[str] = []
    for m in _CERT_TOKENS.finditer(text):
        tok = re.sub(r"\s+", " ", m.group(0)).strip()
        canon = {"PMI-PMP": "PMP", "PMP": "PMP", "PRINCE2": "PRINCE2",
                 "ISO 27001": "ISO 27001", "ISO 9001": "ISO 9001"}.get(tok.upper(), tok)
        if canon.lower() not in (h.lower() for h in hits):
            hits.append(canon)
    return Field(hits, f"{len(hits)} token(s) matched", "tokens:registry") if hits else Field(None)


def _extract_skills(text: str) -> Field:
    """Bullets under a skills heading, plus technology lists after 'Technologies:'."""
    lines = _lines(text)
    out: list[str] = []
    in_skills = False
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if _SKILL_HEADING.match(s):
            in_skills = True
            continue
        if _is_section_heading(s) and not _SKILL_HEADING.match(s):
            in_skills = False
            continue
        m = re.match(r"technologies\s*:\s*(.+)", s, re.IGNORECASE)
        if m:
            out += [t.strip() for t in re.split(r"[·|,]", m.group(1)) if t.strip()]
            continue
        if in_skills:
            item = _BULLET.sub("", s).strip(" ·|,")
            if item and len(item) < 70:
                out.append(item)
    seen: set[str] = set()
    skills = [s for s in out if not (s.lower() in seen or seen.add(s.lower()))]
    return Field(skills[:40], f"{len(skills)} skill item(s)", "heading:bullets") if skills else Field(None)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


SUPPORTED_SUFFIXES = (".pdf", ".docx", ".doc", ".txt", ".md")


def load_document_text(path: str | Path) -> str:
    """Extract the text layer from a CV file.

    Only text-layer extraction is attempted. A scanned PDF yields little or no
    text; the caller detects that (see :meth:`CVExtraction.warnings`) rather than
    silently producing a near-empty record. OCR is deliberately not wired in:
    it is slow and lossy, and for a bench of a few dozen CVs a human re-typing
    one scanned page is cheaper than the failure modes OCR introduces.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported CV format {suffix!r}; expected one of {SUPPORTED_SUFFIXES}")
    if suffix == ".docx":
        import docx  # python-docx
        doc = docx.Document(str(p))
        parts = [par.text for par in doc.paragraphs]
        for table in doc.tables:                 # World Bank forms are tables
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        # Headers and footers are the single most common home for a contact
        # block; document.paragraphs does not include them.
        for section in doc.sections:
            for part in (section.header, section.footer,
                         section.first_page_header, section.first_page_footer):
                parts.extend(par.text for par in part.paragraphs)
        return "\n".join(parts)
    if suffix == ".doc":
        raise ValueError("legacy .doc is not supported; save as .docx or PDF")
    if suffix == ".pdf":
        try:
            import pymupdf as fitz            # PyMuPDF >= 1.24 preferred name
        except ImportError:                   # pragma: no cover - older installs
            import fitz
        with fitz.open(str(p)) as pdf:
            return "\n".join(page.get_text() for page in pdf)
    return p.read_text(encoding="utf-8", errors="replace")


def extract_cv_file(path: str | Path) -> CVExtraction:
    """Load a CV file and extract the bench fields, adding an OCR hint if empty."""
    text = load_document_text(path)
    ext = extract_cv(text)
    if len(text.strip()) < 200:
        ext.warnings.append(
            "very little text extracted — the file is probably a scan without a "
            "text layer; enter this CV manually or run OCR"
        )
    return ext


def extract_cv(text: str) -> CVExtraction:
    """Extract bench fields from raw CV text. Deterministic; no network."""
    text = str(text or "")
    email = _extract_email(text)

    wb_roles = _extract_roles_wb(text)
    narrative_roles = _extract_roles_narrative(text)
    roles = wb_roles or narrative_roles
    genre = ("worldbank-form" if wb_roles
             else "narrative" if narrative_roles
             else "unknown")

    ranges = find_date_ranges(text)
    derived = _years_from_ranges(ranges)
    stated = _stated_years(text)

    name = _extract_name(text, email.value if isinstance(email.value, str) else None)

    ext = CVExtraction(
        full_name=name,
        current_role=_extract_current_role(
            text, roles, name.value if isinstance(name.value, str) else ""),
        years_experience=derived,
        certifications=_extract_certifications(text),
        skills=_extract_skills(text),
        email=email,
        phone=_extract_phone(text),
        employer=_extract_employer(text, roles),
        education=_extract_education(text),
        roles=roles,
        stated_years=stated,
        genre=genre,
    )

    if stated.value and derived.value:
        d, s = float(derived.value), float(stated.value)   # type: ignore[arg-type]
        if abs(d - s) >= 3:
            ext.warnings.append(
                f"derived {d}y from date ranges but the CV states {int(s)}+y — "
                f"check for unlisted early roles")
    if derived.value and float(derived.value) > 45:        # type: ignore[arg-type]
        ext.warnings.append(
            f"derived {derived.value}y exceeds a plausible career span; "
            f"a date range may have been mis-read")
    if not roles:
        ext.warnings.append("no employment history located — check the layout")
    return ext
