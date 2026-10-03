# QuantumCrewBD — End-to-End Development Plan

**Document Version:** 1.0.0
**Prepared by:** dev-001 (Aiaz) — Dev Agent
**Date:** 2026-10-03
**Governing sources:** `01-Received/quantumcrewbd_master_mvp_specification.md` + `..._product_requirements_document_prd.md` (clean originals, v2.0.0)
**Supporting (lossy):** `01-Received/QuantumCrewBD_Autonomous_Engineering_Design_Implementation_Plan_v1.0.0.md`, `..._Engineering_Implementation_Strategy_Execution_Plan_v1.0.0.md`

---

## 0. Status Verdict

| ✅ Working | 🔴 Blocking | ⚠️ Watch |
|---|---|---|
| CrewAI PAT — **valid** (base `app.crewai.com/crewai_plus/api/v1`) | No **LLM API key** yet (Groq / CommandCodeAI) | Phase 2 ≤90 s latency budget is tight |
| Supabase PAT — **valid**, project `QuantumCrewBD` ACTIVE_HEALTHY (pg 17.11, ap-northeast-2) | Phase-1 doc pins are **stale** — install fails as written | `async_execution` ≠ true parallel fan-out |
| DDL via Management API — **verified** (`POST /database/query` → 201) | | DDG rate limits / flakiness |
| Runtime Python 3.11 + 3.12 + `uv` present | | RLS vs. agent server-side queries (see §2.1) |
| Dep stack resolves & imports clean (16 s) | | Streamlit Cloud 1-CPU limits for CrewAI |

**Bottom line:** infrastructure is ready to build on. **One blocker** (LLM key) and **four doc-defects** must be corrected before code is written — writing the code as the docs specify produces a system that does not run.

---

## 1. Document Analysis (in the requested order)

### 1.1 Master MVP Specification v2.0.0 — *the authoritative build spec*

The most complete document. Defines: problem statement, 4-table Supabase schema with full DDL + RLS, 5-agent roster with input/output **contracts**, the Pattern-1 two-phase HITL flow, `tools.py` reference implementation, 4-tab Streamlit layout, and a 5-stage delivery roadmap (M1–M5, ~3 h 45 m).

**What's strong:** the DDL is sound and directly executable; agent output contracts are named and typed (`RFPComplianceDossier`, `MarketIntelligenceDossier`, `ResourceAndConsortiumDossier`, `DraftProposalDossier`, `FinalSubmissionDossier`) — these give us clean Pydantic models and therefore testable handoffs.

**What it lacks:** no test strategy beyond verification gates, no error/fallback taxonomy beyond DDG, no deployment target.

### 1.2 PRD v2.0.0 — *the requirements authority*

Adds what the MVP omits: named personas (Bilal/Sana/Tariq) with journeys, FR-01…FR-13 with MoSCoW priority (P0 = MVP, P1 = v1.1, P2 = roadmap, plus explicit out-of-scope), NFR latency budgets, the 4-Dimension Quality Acceptance Gates (Evidence/Accuracy/Completeness/Quality), the compliance-score + mandays formulas, the 3-minute pitch script, and the M1–M5 day-1 timeline.

**Critical:** §7.1 P0 defines exactly what "done" means for the hackathon. §7.4 gives three explicit exclusions (no portal auto-submission, no ERP/accounting, no native mobile) — these are scope fences I will defend.

**Conflict:** the PRD's own timeline (§12) contains **both** a 30-min "Implement `database/supabase_client.py`" and a 45-min "M2 Unit test Form TECH-6 parser logic" that the MVP roadmap omits. Net day-1 scope ≈ 4 h.

### 1.3 Engineering Implementation Strategy & Execution Plan v1.0.0 — *approach guidance (lossy)*

Answers "should we hand the MVP to `crewai create crew`?" → **No**, correctly. Argues for **Modular Bottom-Up Construction** in 5 phases matching the MVP roadmap. Its real value is the **risk list in §1.2**: context-window truncation, hallucinated/deprecated imports, broken callback bridges between CrewAI threads and Streamlit re-renders.

**Those three risks are prophetic** — §2 below shows two of them materialised in the docs themselves.

### 1.4 Autonomous Engineering Design & Implementation Plan v1.0.0 — *dev-agent runbook (lossy)*

The most prescriptive document: exact target file tree, per-phase deliverables, the 8-part Form TECH-6 definition, the six TECH-form section headers, the `crew.py` function signatures, the `step_callback` → monitor routing heuristic, and a **Dev Agent Runbook** (§5) with four defensive-failure rules (DDG 429 fallback, empty-bench vacancy string, no unpicklable CrewAI objects in `st.session_state`, RFP context management).

**Its §5 runbook is the single most valuable engineering content across all four docs** and becomes the basis for our error-handling test suite.

**Lossy:** 115 backslash-escape artifacts; embedded images mangled. Content is readable; character-level detail is not trustworthy. Formulas recovered → `04-Reference/formulas.md`.

### 1.5 Cross-document consistency

The four documents are **mutually consistent on architecture** (5 agents, 2 phases, 4 tables, 4 tabs) and **inconsistent on four technical specifics** — all four are version-drift defects, catalogued below.

---

## 2. Contradiction & Risk Register (severity-ranked)

### 🔴 R-01 — Dependency pins are a generation stale; install fails as written

Docs specify `crewai>=0.80.0`, `crewai-tools>=0.14.0`, `langchain-groq>=0.2.0`. Reality: **crewai is 1.15.23** (1.x rewrite), `crewai-tools` is 1.15.23, `langchain-groq` is 1.1.3.

**Verified failure:** pinning `pydantic==2.13.5` (latest) is *unsatisfiable* — `crewai 1.15.23` requires `pydantic>=2.11.9,<2.13`. Resolver hard-errors.
**Verified fix:** unpin pydantic → resolves to `2.12.5`, full stack installs in **16 s**, all imports clean.

**Impact:** 🔴 blocks Phase 1. **Action:** use our own locked `requirements.txt`, not the doc's.

### 🔴 R-02 — `DuckDuckGoSearchTool` no longer exists

Docs' `tools.py` does `from crewai_tools import DuckDuckGoSearchTool` and instantiates it twice. In crewai-tools 1.15.23 there is **no duckduckgo tool** — the 80 shipped tools include Brave, Serper, Tavily, Exa, Firecrawl, Linkup… but no DDG.

**Impact:** 🔴 both external-discovery tools fail at import. **Action:** own the search layer — wrap the `ddgs` package (9.16.0) in our own `@tool` functions. Also avoids installing `crewai-tools` at all, which hard-pins `crewai==1.15.23` and drags in `pymupdf`, `python-docx`, `pytube` (pytube is an unnecessary, unmaintained dependency).

### 🔴 R-03 — No Groq/LiteLLM path in CrewAI 1.x

Docs specify `ChatGroq(model_name="openai/gpt-oss-120b")` via `langchain-groq`. Verified: crewai 1.15.23 ships providers `anthropic, azure, bedrock, gemini, openai, openai_compatible, snowflake` — **no Groq provider and no litellm dependency** (litellm is not installed).

**Impact:** 🔴 every agent instantiation fails. **Action:** use crewai's native `LLM` with the `openai_compatible` provider + explicit `base_url`/`api_key` (Groq is OpenAI-compatible at `https://api.groq.com/openai/v1`). This *also* makes the LLM backend swappable — which is exactly what we need if we switch to CommandCodeAI.

### 🔴 R-04 — Agent tools querying Supabase will see zero rows under RLS

*This is the most consequential defect and it is not flagged anywhere in the docs.*

`get_supabase_client()` reads `SUPABASE_KEY` from secrets — the **anon** key. Agent tools then `supabase.table("team_cvs").select("*")` **server-side**, with no user session attached. Under `USING (auth.uid() = user_id)`, an unauthenticated anon request has `auth.uid() = NULL` → **returns 0 rows**.

Consequence: Agent 3's internal bench match always reports "no candidates", silently activating external discovery for *every* role and producing a wrong proposal. The PRD's flagship feature (TECH-6 transformation of *internal* staff) never fires.

**Fix options:**

| Option | How | Trade-off |
|---|---|---|
| **A. Propagate user JWT** *(recommended)* | Build a per-run Supabase client with the authenticated user's `access_token`; inject into the tool layer for that run. | Preserves the RLS guarantee the PRD sells. Requires threading a run-scoped client into tools (no global singleton). |
| B. `service_role` key in tools | Bypass RLS server-side; filter `user_id` manually. | Simpler, but **violates FR-01/NFR** and creates cross-tenant-leak risk if any query forgets the filter. |
| C. SQL RPC functions | `SECURITY DEFINER` functions taking no user param, relying on `auth.uid()`. | Still needs (A) for `auth.uid()` to resolve. |

**Verdict: A.** It is the only option that keeps the security claim true, and it is ~20 lines. We keep the global singleton *only* for unauthenticated auth calls (sign-in/sign-up).

### ⚠️ R-05 — "Parallel tracks" are not natively parallel

The PRD/impl docs describe Track A (Market Intel) ∥ Track B (Resource & JV) executing in parallel. CrewAI's `async_execution` is constrained: **at most one async task may be last** in a crew, async tasks cannot appear with async tasks in their `context`, and `ConditionalTask` cannot be async. A naive two-async-task crew **raises a validation error**.

**Fix:** run Agents 2 and 3 as two **single-agent crews** dispatched concurrently from a `ThreadPoolExecutor`, then hand both outputs to the Writer crew. Benefits: true wall-clock parallelism (protects the ≤90 s budget), and clean per-thread `step_callback` routing (each lane knows its own agent, no keyword-guessing heuristic needed).

### ⚠️ R-06 — Latency budget realism

PRD: Phase 1 ≤30 s, Phase 2 ≤90 s. Phase 2 = 4 agents + external DDG searches. DDG search latency and rate limits are the dominant uncontrolled variable; a single agent reasoning loop over a 100-page RFP can itself exceed 30 s.

**Mitigation:** parallel Tracks A/B, `max_iter` caps, per-run search-result caching, strict instruction to Agent 1 to emit a *concise* compliance matrix (per the impl doc's own §5.4 warning), and streaming `step_callback`s so the UI feels live even when total time runs long. **We will measure and report actuals rather than assert the budget is met.**

### ⚠️ R-07 — Streamlit Cloud resource ceiling

Community Cloud gives ~1 CPU / ~2.7 GB. Embedding a multi-agent CrewAI run that also does network I/O inside that process is workable for a demo but risks the "app is over capacity" state during judging. Also, the app is multitenant SaaS with real anon keys — a public URL invites abuse of your LLM quota.

**Mitigation:** demo on this VPS (Docker + Tailscale Funnel, a pattern already proven here) as primary, Streamlit Cloud as fallback. Add a per-user basic rate limit if the URL is public.

### ⚠️ R-08 — No sample tender corpus exists yet

Every acceptance gate references "a sample World Bank SPD tender". None was supplied. Without a fixed corpus, "verification" is not reproducible.

**Action:** I will author 3 synthetic-but-realistic tenders (WB SPD, ADB QCBS, PPRA SBD) stored in `tests/fixtures/`, unless you supply real ones. This makes every gate deterministic and re-runnable.

### ℹ️ R-09 — Minor inconsistencies

- Package dir named `quantumcrew_bd/` in the impl doc, `quantumcrew_bd` vs `quantumcrewbd` elsewhere → standardise on `quantumcrewbd/`.
- Form TECH-5 is described as "Work Schedule & Deliverables" in §4 but as "Team Composition" in one MVP table row → TECH-6 is the CV form; the §4 section-header list is correct.
- `internal_cv_search(query, min_years)` and `internal_partner_search(domain_or_cert)` accept a `query`/`domain` argument that the reference implementation **never uses** — it returns the entire table. Real filtering must be added or the args removed from the tool schema (LLM-visible tool schemas must not advertise arguments that do nothing).

---

## 3. Verified Environment & Access Inventory

All lines below were executed and observed in this session — not assumed.

### 3.1 Credentials

| Asset | Status | Evidence |
|---|---|---|
| **Supabase PAT** | ✅ valid | `GET /v1/projects` → 200, project `QuantumCrewBD` `qukqelcqngvlplayhjtp`, ACTIVE_HEALTHY, pg 17.11, region ap-northeast-2 |
| **Supabase keys** | ✅ retrieved | anon (`sb_publishable_…`), secret/service_role (`sb_secret_…`), legacy anon + service_role — all available via Management API |
| **Supabase DDL path** | ✅ verified | `POST /v1/projects/{ref}/database/query` → **201**; public schema currently **0 tables**, 27 auth tables |
| **CrewAI PAT** | ✅ valid | `GET https://app.crewai.com/crewai_plus/api/v1/crews` → 200; bogus token → 401 |
| **CrewAI scope** | ⚠️ empty account | `/crews [ ]`, `/skills 0`, `/tools 0`, `/agents 0` — PAT works, workspace has no content |
| **LLM API key** | 🔴 missing | no `GROQ_API_KEY`/`llm` entry anywhere on the box (env, kpass, *.toml, all profiles) |
| **Streamlit Cloud creds** | 🔴 none | no `~/.streamlit/credentials.toml`, no cloud token; only `machine_id_v4` (local telemetry). CLI not installed. |

**Note on the CrewAI PAT:** base URL is **`https://app.crewai.com`** (`/crewai_plus/api/v1/…`). `https://api.crewai.com` is a *different* service (deployment/"Ferry") that requires an internal `x-internal-api-key` header and is not what the PAT authenticates. Worth knowing so nobody wastes time debugging the wrong host.

**Note on Streamlit:** no account credentials exist, but **nothing is blocked by that** — Streamlit is a local Python framework, not a required SaaS account. We install it into the venv. A *hosting* credential is only needed if we deploy to Community Cloud.

### 3.2 Runtime

| Item | Value |
|---|---|
| Python 3.11 / 3.12 | ✅ both present (3.14 also present but **excluded** by policy — CrewAI requires `<3.14`) |
| `uv` 0.11.21 | ✅ |
| Host | 6 vCPU, 11 GiB RAM (5.3 GiB available), 40 GB free on `/` — ample |
| Outbound | ✅ Groq API 401 (=reachable), Supabase, PyPI, DuckDuckGo, Streamlit Cloud all reachable |
| Verified install | `crewai 1.15.23`, `streamlit 1.65.0`, `supabase 2.32.0`, `ddgs 9.16.0`, `pymupdf 1.28.2`, `pydantic 2.12.5` — **16 s**, all imports OK, `crewai` CLI 1.15.23 works |

---

## 4. Decisions Required

Each with a verdict, per your standing rule.

### D-1. CrewAI version → **pin `crewai==1.15.23`** ✅
Only defensible choice: it is what installs cleanly and what the R-02/R-03 fixes target. The docs' `>=0.80.0` floor is meaningless now that 1.x exists. **Pinned exactly** — never a range, because 1.x has already broken the tool API twice.

### D-2. Search layer → **own it (`ddgs`)** ✅
`crewai-tools` has no DuckDuckGo tool, and installing it hard-pins crewai and pulls an unmaintained `pytube`. Wrapping `ddgs` is ~30 lines and gives us the 429-fallback behaviour the runbook demands. We add `pymupdf` directly for PDF ingestion (P1 FR-08 anyway).

### D-3. LLM backend → **`crewai.LLM` + `openai_compatible` provider** ✅
Mandatory (R-03), and it makes the backend swappable, which is what lets us start on CommandCodeAI and move to Groq (or vice versa) by changing 3 env vars.

Provider config shape:
```python
LLM(model=MODEL_NAME, provider="openai_compatible",
    base_url=BASE_URL, api_key=API_KEY)
```
Env contract: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL_NAME`.

**Model recommendation** (you asked, then deferred — recorded for when you return to it):

| Candidate | Why | Caveat |
|---|---|---|
| `openai/gpt-oss-120b` (Groq) | The docs' choice: very fast, cheap, strong tool-calling, 120B-class reasoning | Free tier rate-limits; keys are per-project |
| `openai/gpt-oss-20b` (Groq) | ~2× faster if latency budget bites | Weaker on long-RFP deconstruction |
| A strong Claude/GPT hosted model | Best instruction-following for TECH-form structure | Slower + pricier → threatens ≤90 s |

**Verdict:** build against the `openai_compatible` abstraction and **make the model an env var**, so the choice is a config change, not a code change. Start on whatever the CommandCodeAI key exposes; the abstraction means we're not locked in.

### D-4. RLS strategy → **Option A, per-run user-scoped client** ✅
See R-04. The security claim in the PRD is a headline feature; option B quietly falsifies it.

### D-5. Parallelism → **two concurrent single-agent crews** ✅
See R-05. Native async can't express the topology the docs want.

### D-6. Repo location → **needs your call** ⚠️
I have a valid PAT for GitHub account **`aiazq`**. Options: (a) `aiazq/QuantumCrewBD` private + add Ali/Durre/Saad as collaborators; (b) a GitHub **org** (cleaner for a 4-person team + hackathon judging). Recommend **(b)** if the team has an org — org-owned repos survive team churn and are what judges expect to see.

### D-7. Demo hosting → **VPS + Docker first, Streamlit Cloud as fallback** ⚠️
See R-07. This box already runs the pattern (Tailscale Funnel + Docker). Recommend hosting here for the demo so the LLM quota isn't exposed on a public anonymous URL.

### D-8. Test corpus → **I author 3 synthetic tenders** ✅ (unless you send real ones)
See R-08. Unblocks every acceptance gate immediately and makes them deterministic. If you have a real World Bank SPD pack, send it and I'll use it *plus* the synthetic ones.

---

## 5. Target Architecture (as-built)

```
quantumcrewbd/
├── .streamlit/{config.toml, secrets.toml}     # theme + LLM/Supabase creds (gitignored)
├── database/
│   ├── schema.sql                             # 4 tables + RLS + trigger  ← MVP DDL, verbatim + fixes
│   └── supabase_client.py                     # singleton (auth) + per-run user-scoped client  ← R-04 fix
├── agents/{analyzer,market_intel,resource_planner,writer,reviewer}.py
├── tools.py                                   # @tool: internal_cv_search, internal_partner_search,
│                                              #   external_talent_discovery, external_partner_discovery (R-02 fix)
├── llm.py                                     # LLM factory: openai_compatible (R-03 fix)
├── crew.py                                    # run_analyzer_phase() | run_proposal_generation_phase()
├── ui/collaboration_board.py                  # CollaborationMonitor + ReAct trace tabs
├── app.py                                     # Auth gateway + 4 tabs + Pattern-1 checkpoint
├── tests/                                     # pytest: fixtures, unit, integration, e2e
├── requirements.txt                           # our pins (R-01 fix)
└── README.md
```

**Two-phase data contract** (the spine of the system):

```
Phase 1  raw_rfp_text ─► Agent1 ─► RFPComplianceDossier
                                      │  (framework, mandatory_forms, compliance_matrix,
                                      │   personnel_mandates, teaming_mandates)
                    ┌─────────────────┴──────────────────┐
                    │  🛑 HITL CHECKPOINT (Streamlit)    │
                    │  confirm/override framework        │
                    │  inject CVs / partner directives    │
                    │  [🚀 Authorize Phase 2]             │
                    └─────────────────┬──────────────────┘
Phase 2   ┌──────────────────────────┴─────────────────────┐
          │ Track A: Agent2 (market intel)   ─┐  (concurrent)
          │ Track B: Agent3 (resourcing, TECH-6) ─┐        │
          └──────────────────┬───────────────────┘        │
                             ▼                            │
                     Agent4 (writer, TECH-1..6)            │
                             ▼                            │
                     Agent5 (4-dim audit + score)          │
                             ▼                            │
              persist ─► proposals table ─► Audited Bid Studio
```

---

## 6. Execution Plan

Seven phases. Each has an **acceptance gate** that is *executed*, not asserted. Day-1 hackathon scope is M1–M5 (≈4 h); P6–P7 extend to demo-ready and maintainable.

### Phase 1 — Foundation & Persistence *(~40 m)*
- `requirements.txt` with our verified pins (D-1).
- `database/schema.sql`: the MVP DDL **plus** two fixes — add the missing `WITH CHECK` on `profiles` (present) and verify the `handle_new_user()` trigger body is properly formatted (the lossy doc showed it collapsed onto one line).
- `database/supabase_client.py`: dual-mode factory — `get_supabase_client()` (anon, no session) and `get_user_client(access_token)` (RLS-scoped) → **R-04**.
- **Gate 1 (automated):** apply `schema.sql` via Management API; assert 4 tables + 4 policies exist; `pg_policies` count = 4. Create 2 auth users; assert user A sees 0 of user B's rows on all 3 tenant tables; assert `INSERT` with a mismatched `user_id` is **rejected** by `WITH CHECK`.

### Phase 2 — Sourcing & Search Tool Suite *(~45 m)*
- 4 `@tool` functions on `ddgs` + Supabase, with **real** filtering (fixes R-09) and the runbook's fallbacks: DDG 429/empty → generalised query; empty bench → the exact `[INTERNAL BENCH VACANCY: …]` warning string that triggers external discovery.
- Tools receive a **run-scoped user client** (D-4).
- **Gate 2:** unit tests per tool against mocked HTTP + live smoke test; assert no unhandled exception on a forced 429; assert vacancy string exact-match.

### Phase 3 — The 5 Agent Modules *(~45 m)*
- Each agent: Role / Goal / Backstory / tools / native `LLM` (D-3). Writer enforces the six TECH-form headers verbatim; Resource Planner enforces the 8-part TECH-6 structure; Reviewer computes the compliance score and re-computes Total Mandays.
- Pydantic output models mirroring the five dossiers → makes handoffs type-checked and testable.
- **Gate 3:** contract tests — each agent's declared output keys match the downstream consumer's expected input keys. Run each agent once against a fixture; validate JSON parses into its model.

### Phase 4 — Orchestration & Callback Bridge *(~35 m)*
- `run_analyzer_phase()` / `run_proposal_generation_phase()` + `ThreadPoolExecutor` fan-out for Tracks A/B (D-5).
- `step_callback` → `CollaborationMonitor` routing; thread-safe event queue so Streamlit re-renders safely (impl-doc risk #3).
- **Gate 4:** headless two-phase run; assert Phase-1 output parses into Phase-2 input; assert no state corruption; measure per-phase wall-clock and record actuals against ≤30 s / ≤90 s.

### Phase 5 — Streamlit UI & HITL Cockpit *(~60 m)*
- Auth gateway; 4 tabs; the Pattern-1 checkpoint (Section A framework dropdown / Section B mandates + CV injection / Section C authorize button); `CollaborationMonitor` with two lanes, inline tickers, ReAct drawers.
- **`st.session_state` holds only JSON-serialisable data** — never CrewAI objects (runbook rule 3).
- **Gate 5:** headless browser E2E — sign up → add bench member → ingest RFP → confirm framework → watch execution → download `.md`/`.txt`. Screenshot evidence.

### Phase 6 — Verification & Hardening *(~45 m)*
- Full E2E on all 3 fixture tenders (WB/ADB/PPRA) → assert the correct form set is emitted per framework.
- **RLS isolation re-verified from the app layer**, not just SQL.
- Latency report: actual vs. budget, stated plainly.
- **Gate 6:** the FR-01…FR-07 P0 checklist, each item marked ✅ verified / ⚠️ partial / 🔴 not met — with the evidence line next to it.

### Phase 7 — Deploy & Handover *(~40 m)*
- Dockerfile + compose; deploy to this VPS behind Tailscale Funnel (D-7); secrets via env, never in the image.
- `README.md` runbook + credentials recorded in KeePassXC (per your convention, with expiry notes).
- **Gate 7:** public/staging URL returns the app; a cold-start run completes; teardown documented.

---

## 7. Test Strategy

| Layer | Tooling | What it proves |
|---|---|---|
| Unit | `pytest` + `respx` (HTTP mocking) | Tool filtering, fallbacks, TECH-6 formatter, score + mandays math |
| Contract | `pytest` + Pydantic | Agent output ↔ downstream input key compatibility |
| Integration | live Supabase (test project/schema) + mocked LLM | Tools↔DB under RLS |
| Security | SQL assertions via Management API | RLS isolation across 2+ users; cross-tenant INSERT rejected |
| E2E | Streamlit headless + Playwright | Full user journey, 4 tabs, download artifacts |
| Perf | wall-clock instrumentation | Actual vs. ≤30 s / ≤90 s / ≤250 ms |

**Discipline:** RED→GREEN→REFACTOR per module. **No module is "done" on local green tests alone** — golden-path E2E on the deployed target is the bar, and I will state plainly what is still running old code and what remains unverified.

---

## 8. What I Need From You

| # | Item | Blocks | Notes |
|---|---|---|---|
| 1 | **LLM API key** + base URL + model name | Phase 3 | CommandCodeAI key you mentioned. Any OpenAI-compatible endpoint works (`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME`). **Only true blocker.** |
| 2 | **GitHub repo decision** (D-6) | Phase 7 | `aiazq/QuantumCrewBD`, or org; + collaborator handles for Ali/Durre/Saad |
| 3 | **Sample tenders?** (D-8) | Gate 5/6 | Else I author 3 synthetic WB/ADB/PPRA fixtures |
| 4 | **Hosting target confirm** (D-7) | Phase 7 | Recommend this VPS + Funnel |
| 5 | *(optional)* Supabase **DB password** | — | **Not needed** — all DDL/verification runs via the Management API PAT |
| 6 | *(optional)* Streamlit Cloud account | — | Only for the fallback hosting path |

---

## 9. Verdict

**What I'd ship:** the corrected stack — `crewai==1.15.23` + native `openai_compatible` LLM + in-house `ddgs` tools + user-JWT-scoped Supabase client + two concurrent track crews — built bottom-up in the 5 doc phases, with gates executed rather than asserted. That ordering is right: the docs' instinct to build persistence → tools → agents → orchestrator → UI is exactly correct, and it front-loads the two things that are hardest to retrofit (RLS correctness and the callback bridge).

**What I would not do:** install the doc's `requirements.txt` (it fails), use `DuckDuckGoSearchTool` (doesn't exist), use `ChatGroq` (no Groq provider in 1.x), wire agent tools to the anon key (silently returns zero rows — the flagship TECH-6 feature would never fire), or trust the ≤90 s Phase-2 budget until it's measured.

**Sequence:** send the LLM key and I start Phase 1 immediately — it needs no LLM key at all, so I can have schema deployed, RLS isolation proven across two accounts, and the tool suite unit-tested before the key even arrives.

---

*Prepared as source-of-truth Markdown (editable, git-diffable). Generated DOCX/PDF exports should be treated as derived artifacts.*
