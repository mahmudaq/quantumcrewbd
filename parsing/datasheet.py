"""Deterministic tender extraction — no LLM involved.

Why this module exists (defect R-11)
------------------------------------
A naive "feed the whole PDF to the LLM and ask for the mandatory criteria"
pipeline **hallucinated the pass mark**. On a live tender whose true technical
passing mark is 45, the model reported 70; on the Data Sheet where 45 is stated
explicitly, it answered "not specified". Both errors are disqualifying: the pass
mark determines whether a bid is even opened.

The fix is to stop asking the model to *search* and start giving it only the
text that matters. Everything in this module is pure Python over extracted text:

  locate_data_sheet(text)   -> the Data Sheet / ITDS region, or None
  find_pass_mark(text)      -> (mark, evidence, strategy) or None
  find_selection_method(t)  -> "QCBS" / "QBS" / ... or None
  find_evaluation_marks(t)  -> {"technical": 100, "passing": 45}

The LLM is then handed the located passage and asked to *reason* about it, never
to go looking for the number. Every extractor returns the evidence string it
matched on, so a wrong answer is auditable rather than merely wrong.

Measured against the local corpus (4 real tenders):
  DOC-1 Lakki Sanitation  -> 70   (stated "seventy (70) points")
  DOC-2 Naurang DWSSS     -> 70   (same standard form)
  DOC-3 Naran Feasibility -> 45   (evaluation table "Passing Marks 45")
  DOC-4 World Bank SPD    -> form-based, no national pass-mark table
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# --------------------------------------------------------------------------- #
# Number words — donors write "seventy (70)" as often as "70"
# --------------------------------------------------------------------------- #

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_WORD_ALT = "|".join(_NUMBER_WORDS)
_UNITS = "|".join(k for k in _NUMBER_WORDS if _NUMBER_WORDS[k] < 10)
# "seventy (70)", "forty-five (45)", "forty five (45)" — but ONLY when the
# parenthetical is followed by a scoring unit. Without that requirement this
# pattern matches contract boilerplate: "at least thirty (30) days' written
# notice of termination" is a notice period, not a pass mark. Verified false
# positive on DOC-3 before this guard was added.
_SPELLED_WITH_DIGIT = re.compile(
    rf"\b({_WORD_ALT})(?:[-\s]({_UNITS}))?"
    rf"\s*\(\s*(\d{{1,3}})\s*\)",
    re.IGNORECASE,
)

# What may legitimately follow a pass-mark number.
_SCORE_SUFFIX = re.compile(r"\s*(?:points?|marks?|score|%)", re.IGNORECASE)
# Units that prove the number is NOT a score when they follow it.
_NON_SCORE_SUFFIX = re.compile(
    r"\s*(?:days?|weeks?|months?|years?|hours?|minutes?|business\s+days?|"
    r"calendar\s+days?|percent\s+of|pages?|copies?|staff|personnel|experts?)\b",
    re.IGNORECASE,
)


def _is_score_context(text: str, match_end: int) -> bool:
    """True when the text right after a number marks it as a score."""
    tail = text[match_end: match_end + 24]
    if _NON_SCORE_SUFFIX.match(tail):
        return False
    return bool(_SCORE_SUFFIX.match(tail))


def _word_to_int(word: str, unit: str | None) -> int | None:
    """'seventy' -> 70; ('forty','five') -> 45."""
    base = _NUMBER_WORDS.get(word.lower())
    if base is None:
        return None
    if unit:
        u = _NUMBER_WORDS.get(unit.lower())
        if u is not None and base >= 20:
            return base + u
    return base


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PassMarkResult:
    """A located pass mark plus the text that proves it."""

    mark: int
    evidence: str          # the exact matched substring, for audit
    strategy: str          # which pattern fired — makes regressions diagnosable
    location: str = "unknown"   # "data_sheet" | "evaluation_table" | "body"

    def __bool__(self) -> bool:  # allows `if find_pass_mark(t):`
        return True


@dataclass
class DataSheetResult:
    """The located Data Sheet region and whatever could be read out of it."""

    text: str
    start: int
    end: int
    heading: str
    pass_mark: PassMarkResult | None = None
    selection_method: str | None = None
    technical_marks: int | None = None
    forms_required: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text.strip())


# --------------------------------------------------------------------------- #
# Data Sheet location
# --------------------------------------------------------------------------- #

# Ordered most-specific first. The Data Sheet is the authoritative source: it is
# the one place donors state the pass mark as a number rather than prose.
_DATA_SHEET_HEADINGS: tuple[re.Pattern[str], ...] = (
    # `[ \t]*` not `\s*`: with re.MULTILINE, `\s*` after `^` eats the preceding
    # newline and reports the match one line too early. The heading offset is
    # used for slicing, so it has to point at the "D", not the blank line.
    re.compile(r"^[ \t]*DATA\s+SHEET[ \t]*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[ \t]*Instruction[s]?\s+to\s+Consultants\s*[-–—:]?\s*Data\s+Sheet",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[ \t]*ITDS\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[ \t]*Appendix\s+[A-Z]\b.*Data\s+Sheet", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^[ \t]*Section\s+\d+.*Data\s+Sheet", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bData\s+Sheet\b", re.IGNORECASE),
)

# A Data Sheet ends when the next major section begins.
_SECTION_BREAK = re.compile(
    r"^\s*(?:Section\s+\d|Appendix\s+[A-Z]\b|Annex\s+[A-Z]?\b|"
    r"Technical\s+Proposal\s*[-–—]\s*Standard\s+Forms|"
    r"Form\s+TECH-\d|PART\s+[IVX]+)",
    re.IGNORECASE | re.MULTILINE,
)

_MAX_SHEET_CHARS = 60_000


def locate_data_sheet(text: str, *, max_chars: int = _MAX_SHEET_CHARS) -> DataSheetResult | None:
    """Return the Data Sheet region, or ``None`` if the document has none.

    Returns ``None`` rather than guessing: a caller that cannot find a Data Sheet
    must not silently fall back to a hallucinated number. DOC-4 (World Bank SPD
    for a training firm) legitimately has no national pass-mark table, and
    treating that as failure would be wrong.
    """
    if not text or not text.strip():
        return None

    for pattern in _DATA_SHEET_HEADINGS:
        m = pattern.search(text)
        if not m:
            continue

        start = m.start()
        # Find where the sheet ends, scanning only within a sane window.
        window_end = min(len(text), start + max_chars)
        nxt = _SECTION_BREAK.search(text, m.end(), window_end)
        end = nxt.start() if nxt else window_end

        body = text[start:end]
        if len(body.strip()) < 40:      # a stray mention, not a real section
            continue

        return DataSheetResult(text=body, start=start, end=end,
                               heading=m.group(0).strip())

    return None


# --------------------------------------------------------------------------- #
# Pass mark
# --------------------------------------------------------------------------- #

# Ordered by reliability. Each entry: (strategy name, compiled pattern).
# The patterns deliberately require wording that ties the number to a PASSING
# threshold — a bare "\d+" anywhere in the document is how 70 got invented.
_PASS_MARK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "Passing Marks\n45"  (KP/PPRA evaluation tables)
    ("passing_marks_table",
     re.compile(r"Passing\s+Marks?\s*[:\-–—]?\s*\n?\s*(\d{1,3})\b", re.IGNORECASE)),
    # "technical score equal or more than seventy (70) points"
    ("score_equal_or_more_than",
     re.compile(r"technical\s+score\s+equal\s+or\s+more\s+than\s+"
                r"(?:[a-z\-]+\s*)?\(?\s*(\d{1,3})\s*\)?", re.IGNORECASE)),
    # "minimum technical score of 70" / "minimum qualifying marks: 70"
    ("minimum_technical_score",
     re.compile(r"minimum\s+(?:qualifying\s+|technical\s+)?(?:score|marks?)"
                r"\s*(?:of|is|:|=)?\s*(\d{1,3})\b", re.IGNORECASE)),
    # "shall be 70 points" / "at least seventy (70) points"
    ("at_least_points",
     re.compile(r"(?:at\s+least|not\s+less\s+than|no\s+less\s+than)\s+"
                r"(\d{1,3})\s*(?:points|marks)", re.IGNORECASE)),
    # "70 points or above"
    ("points_or_above",
     re.compile(r"(\d{1,3})\s*(?:points|marks)\s+or\s+(?:above|more|higher)",
                re.IGNORECASE)),
)

# A Data Sheet line like "19.4 ... technical score equal or more than
# seventy (70) points" — the spelled form carries the number in parentheses.
_SPELLED_SCORE = re.compile(
    r"(?:equal\s+or\s+more\s+than|at\s+least|minimum(?:\s+of)?|above)\s+"
    r"([a-z\-]+(?:\s+[a-z]+)?)\s*\(\s*(\d{1,3})\s*\)\s*(?:points|marks)?",
    re.IGNORECASE,
)


def _plausible(mark: int) -> bool:
    """A technical pass mark is a percentage-scale threshold."""
    return 30 <= mark <= 95


def find_pass_mark(
    text: str,
    *,
    data_sheet: DataSheetResult | None = None,
) -> PassMarkResult | None:
    """Locate the technical passing mark deterministically.

    Searches the Data Sheet first (authoritative), then the evaluation table
    region, then the body. Returns ``None`` when no pattern fires — callers must
    treat that as "unknown", never as a default.
    """
    if not text or not text.strip():
        return None

    scopes: list[tuple[str, str]] = []
    if data_sheet and data_sheet.text:
        scopes.append(("data_sheet", data_sheet.text))

    # The evaluation-criteria block, where KP/PPRA tables live.
    ev = re.search(r"Evaluation\s+Criteria", text, re.IGNORECASE)
    if ev:
        scopes.append(("evaluation_table", text[ev.start(): ev.start() + 8_000]))

    scopes.append(("body", text))

    for location, scope in scopes:
        # 1. spelled-out form with the digit in parentheses — most explicit.
        for m in _SPELLED_WITH_DIGIT.finditer(scope):
            word, digits = m.group(1), int(m.group(3))
            if not _is_score_context(scope, m.end()):
                continue
            word_parts = word.lower().replace("-", " ").split()
            lib = _word_to_int(word_parts[0], word_parts[1] if len(word_parts) > 1 else None)
            # Accept when the words and the digits agree (or the word is unknown).
            if lib is None or lib == digits:
                if _plausible(digits):
                    return PassMarkResult(digits, m.group(0).strip(),
                                          "spelled_with_digits", location)

        # 2. the ordered numeric patterns
        for strategy, pattern in _PASS_MARK_PATTERNS:
            m = pattern.search(scope)
            if not m:
                continue
            mark = int(m.group(1))
            if not _plausible(mark):
                continue
            # A bare numeric match still has to not be a duration. Patterns
            # already require score wording, but the scope tail is cheap.
            if _NON_SCORE_SUFFIX.match(scope[m.end(): m.end() + 24]):
                continue
            return PassMarkResult(mark, m.group(0).strip(), strategy, location)

    return None


# --------------------------------------------------------------------------- #
# Selection method and evaluation marks
# --------------------------------------------------------------------------- #

_METHODS: tuple[tuple[str, str], ...] = (
    ("QCBS", r"quality\s*(?:and|&)\s*cost\s*based\s*selection|QCBS"),
    ("QBS", r"quality[\s-]*based\s*selection|(?:^|\W)QBS(?:\W|$)"),
    ("CQS", r"consultant'?s?\s+qualifications|(?:^|\W)CQS(?:\W|$)"),
    ("LCS", r"least[\s-]*cost\s*(?:based\s*)?selection|(?:^|\W)LCS(?:\W|$)"),
    ("FBS", r"fixed[\s-]*budget\s*(?:based\s*)?selection|(?:^|\W)FBS(?:\W|$)"),
    ("SSS", r"single[\s-]*source\s*selection|(?:^|\W)SSS(?:\W|$)"),
)


def find_selection_method(text: str) -> str | None:
    """Return the procurement/selection method, e.g. ``"QCBS"``."""
    if not text:
        return None
    for name, pattern in _METHODS:
        if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return name
    return None


def find_envelope_scheme(text: str) -> str | None:
    """'Single Stage Two Envelopes' | 'Single-Stage One-Envelope' | None."""
    if not text:
        return None
    m = re.search(
        r"single[\s-]*stage\s+(one|two|single)[\s-]*envelope[s]?",
        text, re.IGNORECASE)
    if m:
        return "One-Envelope" if "one" in m.group(1).lower() else "Two-Envelope"
    if re.search(r"one[\s-]*envelope", text, re.IGNORECASE):
        return "One-Envelope"
    if re.search(r"two[\s-]*envelope", text, re.IGNORECASE):
        return "Two-Envelope"
    return None


def find_evaluation_marks(text: str) -> dict[str, int]:
    """Technical total and passing marks, when the tender states them."""
    out: dict[str, int] = {}

    m = re.search(r"Technical\s+Marks?\s*[:\-–—]?\s*\n?\s*(\d{1,3})\b",
                  text, re.IGNORECASE)
    if m:
        out["technical"] = int(m.group(1))

    m = re.search(r"Grand\s+Total\s+Marks?\s*[>:]?\s*\n?\s*(\d{1,3})\b",
                  text, re.IGNORECASE)
    if m:
        out["grand_total"] = int(m.group(1))

    pm = find_pass_mark(text)
    if pm:
        out["passing"] = pm.mark
    return out


_TECH_FORM = re.compile(r"\bForm\s+(TECH-\d+)\b", re.IGNORECASE)
_FIN_FORM = re.compile(r"\bForm\s+(FIN-\d+)\b", re.IGNORECASE)

# Donor SPDs present the technical envelope before the financial one, and the
# proposal writer emits sections in the order returned here. Alphabetical
# sorting would put FIN before TECH, which is not the submission order.
_FORM_PREFIX_ORDER = {"TECH": 0, "FIN": 1}


def find_required_forms(text: str) -> list[str]:
    """Standard submission forms actually cited by the document, in SPD order.

    Order: TECH-n before FIN-n, and numerically within each prefix, so TECH-10
    follows TECH-2 rather than preceding it. The numeric group is `\\d+`, not
    `\\d`, or TECH-10 would truncate to TECH-1.
    """
    if not text:
        return []
    found = {m.group(1).upper() for m in _TECH_FORM.finditer(text)}
    found |= {m.group(1).upper() for m in _FIN_FORM.finditer(text)}
    return sorted(
        found,
        key=lambda f: (_FORM_PREFIX_ORDER.get(f.split("-")[0], 9), int(f.split("-")[1])),
    )


# --------------------------------------------------------------------------- #
# Framework detection (tuple, not donor-name lookup)
# --------------------------------------------------------------------------- #

# The spec is explicit: identify the framework by its *structure*, not by the
# donor's name appearing somewhere in the text. Donor names are unreliable —
# a PPRA tender cites the World Bank SPD, and a World Bank SPD can be used by a
# national agency.
def detect_framework(text: str) -> dict[str, object]:
    """Identify the governing framework from structural markers."""
    if not text:
        return {"framework": "Unknown", "confidence": "low", "signals": []}

    signals: list[str] = []
    low = text.lower()

    # Count donor *mentions* rather than testing presence. A World Bank SPD
    # routinely names ADB/other multilateral banks as alternative acceptable
    # references, so a bare "ADB" match mislabels the framework. Verified:
    # DOC-4 (World Bank training-firm RFP) contains both names and was
    # classified "ADB QCBS" by a presence test. Whichever donor dominates the
    # document is the governing one.
    wb_hits = len(re.findall(r"world\s+bank|international\s+bank\s+for\s+reconstruction", low))
    adb_hits = len(re.findall(r"asian\s+development\s+bank", low))
    is_wb = wb_hits > 0
    is_adb = adb_hits > 0
    is_ppra = bool(re.search(r"khyber\s+pakhtunkhwa\s+public\s+procurement|"
                             r"public\s+procurement\s+rules|"
                             r"standard\s+bidding\s+documents?\s+for\s+hiring\s+of\s+services",
                             low))
    has_tech_forms = bool(re.search(r"Form\s+TECH-\d", text, re.IGNORECASE))
    has_fin_forms = bool(re.search(r"Form\s+FIN-\d", text, re.IGNORECASE))
    has_data_sheet = bool(re.search(r"DATA\s+SHEET|Data\s+Sheet", text, re.IGNORECASE))

    if has_tech_forms:
        n_tech = len(set(re.findall(r"Form\s+(TECH-\d)", text, re.IGNORECASE)))
        signals.append(f"TECH forms cited ({n_tech} distinct)")
    if has_fin_forms:
        signals.append("FIN forms cited")
    if has_data_sheet:
        signals.append("Data Sheet present")
    if is_ppra:
        signals.append("KP Public Procurement Rules / SBD referenced")
    if wb_hits:
        signals.append(f"World Bank referenced ×{wb_hits}")
    if adb_hits:
        signals.append(f"ADB referenced ×{adb_hits}")

    # Structure first: TECH/FIN forms + Data Sheet = multilateral SPD family.
    if has_tech_forms and has_fin_forms:
        # Dominant donor wins; ties or absence fall back to "unspecified".
        if adb_hits > wb_hits:
            return {"framework": "ADB QCBS", "confidence": "high", "signals": signals}
        if wb_hits > 0:
            return {"framework": "World Bank SPD", "confidence": "high", "signals": signals}
        if adb_hits > 0:
            return {"framework": "ADB QCBS", "confidence": "medium", "signals": signals}
        return {"framework": "Multilateral SPD (donor unspecified)",
                "confidence": "medium", "signals": signals}

    if is_ppra:
        return {"framework": "PPRA SBD", "confidence": "high", "signals": signals}

    if has_tech_forms:
        return {"framework": "Multilateral SPD (partial)", "confidence": "medium",
                "signals": signals}

    return {"framework": "Custom Commercial", "confidence": "low", "signals": signals}
