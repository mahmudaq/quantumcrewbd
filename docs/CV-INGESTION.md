# CV ingestion — bench extraction

Upload a PDF or DOCX on the **Internal Bench** panel and the bench fields are
filled in automatically. You review and correct them, then save.

## Why upload rather than type

The bench (`team_cvs`) is what the resource planner searches to answer "do we
already have someone who can do this?". A bench that was hand-typed is only as
good as the person typing it, and typing six fields per CV is where a
certification gets mistyped or a date range gets inverted.

## How it works

`parsing/cv.py` reads the **text layer** of the file and extracts fields with
deterministic rules. There is no LLM in this path, deliberately:

- the same document always produces the same result
- the demo has no network dependency, so a rate limit cannot break it
- the extraction rules are inspectable and testable

Every extracted value is a *proposal*. The upload form pre-fills each field but
leaves it editable, and the "What was found" panel shows the origin of each
value (`regex:email`, `role:ongoing`, `wb:name-of-staff`, …) so a wrong guess is
visible rather than silently saved.

## Fields extracted

| Field | Method | Reliability |
|---|---|---|
| `full_name` | proximity to the email; World Bank `Name of Staff` cell | high — falls back to the first plausible line above the fold |
| `email` / `phone` | regex, emoji-tolerant | high when present on the CV |
| `current_role` | the title bound to the ongoing role | high |
| `employer` | the employer of the ongoing role, else the header's registered entity | medium — location suffixes are stripped |
| `years_experience` | derived from employment date intervals | medium — see below |
| `certifications` | registry of known credential tokens (PMP, ISO 27001, PEC, …) | medium — only finds credentials it knows |
| `skills` | bullet items under a skills heading, plus `Technologies:` lines | medium — depends on the CV using such a heading |
| `education` | highest ranked degree keyword | low-medium — rank only, not the institution |
| `roles[]` | every employment block: start, end, title, employer, ongoing | high for well-formed dates |

## Years of experience — read this

Nobody writes "12 years of experience" on a CV, so the number is **derived**, not
read. Employment date ranges are parsed into intervals, overlapping intervals are
**merged** (a teaching post held alongside consulting must not double-count), and
the union is measured against today.

Two things to know:

1. **Education and training sections are excluded.** Without that, a degree range
   (`2005 – 2007`) reads as employment. On a real CV this inflated 17 years to 29.
2. **A stated figure is kept separately.** When a CV says "20+ years of
   experience" that is recorded in `stated_years`, and the two are shown side by
   side. A gap of 3+ years triggers a notice rather than a silent average.

If the derived number disagrees with the CV, trust neither blindly — the field is
editable for a reason.

## Known limitations

- **Scanned PDFs** have no text layer. The upload warns rather than saving a
  near-empty record. OCR is deliberately not wired in: it is slow and lossy, and
  re-typing one page is cheaper than the failure modes it introduces.
- **Legacy `.doc`** is rejected with a message telling the user to save as
  `.docx` or PDF.
- **Certifications** come from a token registry. An unusual credential spelling
  may be missed; add it to `_CERT_TOKENS` in `parsing/cv.py`.
- **Skills** are only found under a recognised heading. A prose-only CV yields
  few skills, which is a real limitation of heading-based extraction.
- **Titles are never invented.** Where a CV lists an employer and dates but no
  title (common in older CV sections), the title is left empty.

## Privacy

Real CVs are personal data and live **outside the repository**, in
`../QuantumCrewBD-local-cvs/` — a sibling of the repo directory, unreachable by
git. This mirrors how the reference tenders are kept.

The test suite uses **synthetic fixtures only**. No test contains a real person's
name, employer, email, or phone number.

## Tests

```bash
pytest tests/test_cv_extraction.py -q     # 52 tests
pytest tests/ -q                          # full suite (462)
python scripts/qa_bench_ui.py             # AppTest against the live app.py
python scripts/verify_cv_bench.py --cleanup   # CV -> team_cvs -> read back
python scripts/verify_rls_anon.py             # anon role sees nothing
```

Each test names the bug it locks down. The date-parsing and section-gating tests
are the load-bearing ones: they are what keep the derived experience figure
honest.
