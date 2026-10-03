# QuantumCrewBD

Multi-tenant autonomous bid-production platform for public-procurement
consulting. Ingests a tender document, extracts the evaluation framework and
pass mark **deterministically**, stops at a human checkpoint, then generates a
donor-format compliant proposal with an adversarial compliance audit.

Built for the HEC PakAngels Aspire Hackathon 2 (Cohort 11).

---

## What it does

```
tender text ──► Agent 1: RFP & Compliance Deconstruction
                        │
                        ├─ deterministic Data-Sheet locator (no LLM)
                        │    → framework, pass mark, required forms
                        │
                   ⏸ HITL CHECKPOINT  (framework confirm · CV injection)
                        │
        ┌───────────────┴───────────────┐
   Track A                          Track B          ← run concurrently
   Agent 3: Resource &              Agent 2: Market &
   Consortium Planner               Competitor Intel
        └───────────────┬───────────────┘
                        │
                 Agent 4: Proposal Writer
                        │
                 Agent 5: Compliance & QA Auditor
                        │
              proposal .md + TECH-6 CVs + audit findings
```

---

## The two things that make it correct

**1. Number extraction is deterministic, not LLM-driven.**

A naive "PDF → LLM → JSON" pipeline hallucinates tender figures. Measured
against the reference corpus, it got the pass mark wrong on 2 of 4 documents —
it read DOC-3's 45 as 70, and reported DOC-1's Data Sheet figure as "not
specified" when it is stated. `parsing/datasheet.py` locates the Data Sheet /
ITT section by pattern first and hands the LLM only the located text, so the
model *reasons* over facts instead of searching for them.

| Tender | Truth | Naive LLM | Deterministic |
|---|---|---|---|
| DOC-1 Lakki Sanitation | 70 | ❌ "not specified" | ✅ 70 |
| DOC-2 Naurang DWSSS | 70 | — | ✅ 70 |
| DOC-3 Naran Feasibility | **45** | ❌ **70** | ✅ **45** |

Two false positives were caught by testing against real documents, not
fixtures: DOC-3's "30" came from a *contract notice period* ("thirty (30) days'
written notice of termination"), and DOC-4 read as ADB because a World Bank SPD
*cites ADB as an alternative*.

**2. The HITL checkpoint is a hard stop.**

Agent 1's framework detection decides which form template every downstream agent
uses. A wrong framework produces a complete, well-formatted proposal in the
wrong template — the most expensive possible failure. So Phase 1 stops and a
human confirms before the expensive work starts.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the values
streamlit run app.py
```

Open http://localhost:8501 and sign in.

### Required environment

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | anon/public key — safe for the client |
| `COMMANDCODE_API_KEY` | LLM provider key (or `GROQ_API_KEY`) |
| `LLM_PROVIDER` | `commandcode` (default) or `groq` |

Secrets live in **KeePassXC**, not in the repo. `.env` is gitignored.

---

## Deployment

```bash
docker compose up -d --build
```

The container binds `127.0.0.1:8501` only; public access goes through Tailscale
Funnel. Check it:

```bash
docker compose ps
curl -fsS http://localhost:8501/_stcore/health   # → ok
tailscale serve status
```

Teardown:

```bash
docker compose down            # keeps volumes
```

### Container drift checklist

Every time you suspect the deployment is stale:

```bash
docker ps -a                          # is it actually running?
tailscale serve status                # is Funnel still pointed at it?
docker inspect --format '{{.Created}}' quantumcrewbd
git log -1 --format=%cd               # image must postdate the last commit
```

---

## Configuration (per account)

Tab 4 exposes provider, model and a **live "test this key" button**. The button
makes a real request on purpose: a key can be well-formed and still rejected
(wrong plan, revoked, region-blocked), and the point is to discover that before
a run rather than during one.

Resolution order for the model actually used:

```
per-call override  →  tenant DB setting  →  LLM_MODEL_<AGENT>  →  LLM_MODEL  →  registry default
```

---

## Multi-tenancy

Every table carries `user_id`, RLS policies compare it to `auth.uid()`, and the
column **defaults to `auth.uid()`** so the database stamps ownership and a
client cannot forge it. Verified live: user A sees their own bench row, user B
sees none of it, and a cross-tenant INSERT is rejected.

> R-04: the anon Supabase client sees **zero rows** under RLS. All data access
> must go through `get_user_client(access_token)`.

---

## Tests

```bash
pytest tests/ -q
```

| Layer | Proves |
|---|---|
| Unit | deterministic extraction, TECH-6 formatter, score + mandays maths |
| Contract | agent output keys ↔ downstream input keys |
| Orchestration | event bridge thread-safety, fan-out concurrency, phase handoff |
| Live gates | real LLM per agent; real sign-in; RLS from the app layer |

Local green tests are the floor, not the bar: the live gates are what prove a
real model emits parseable JSON, and those results are reported separately.

---

## Latency budgets

| Stage | Budget |
|---|---|
| Phase 1 (analysis) | ≤ 30 s |
| Phase 2 (generation) | ≤ 90 s |
| DB reads | ≤ 500 ms |

Actuals are recorded per run and shown in the Execution tab — reported, not
asserted.

---

## Known constraints

- **Groq free tier is 8,000 TPM**; a full tender (~23k tokens) returns HTTP 413.
  The default provider (CommandCode) accepts a whole tender in one call.
- **DeepSeek peak pricing** applies 01–04 and 06–10 UTC (06:00–09:00 and
  11:00–15:00 PKT) — budget ≈ $0.09–0.18 per bid.
- Sample tenders are **not in this repo** (they contain client data). Point
  `QC_TENDERS_DIR` at a local directory to run the E2E suite.

---

## Layout

```
app.py                     Streamlit UI (4 tabs, HITL checkpoint)
agents/                    the five agent modules + shared construction
models/dossiers.py         Pydantic contracts between agents
parsing/datasheet.py       deterministic tender extraction (R-11 fix)
parsing/tech6.py           8-part donor CV formatter
parsing/scoring.py         compliance score + level-of-effort maths
orchestration/pipeline.py  two-phase run, Track A/B fan-out
orchestration/monitor.py   thread-safe CrewAI → UI event bridge
llm/                       provider registry, resolver, CrewAI factory
database/                  Supabase clients (user-scoped), schema
supabase/migrations/       schema source-of-truth
tests/                     unit + contract + orchestration
```
