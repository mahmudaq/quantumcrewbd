# QuantumCrewBD — Project Notes

## Context

Hackathon project (**HEC PakAngels Aspire Hackathon 2, Cohort 11**) — enterprise multi-agent
procurement intelligence & proposal synthesis SaaS. Dev owner: **dev-001 (Aiaz)**.

- **Strategic Lead:** Dr. Irfan Ahmed Khan
- **Project Lead:** Mahmud Qureshi (mahmudaq)
- **Core Engineering Team:** Ali Uddin Khan, Durre Nayab, Saad Saeed
- **Status:** Plan delivered (`02-Sent/`). Awaiting LLM API key to start Phase 3.

## Layout

| Dir | Purpose |
|---|---|
| `01-Received/` | Supplied documents + `PROVENANCE.md` (fidelity notes) |
| `02-Sent/` | Deliverables produced for the team |
| `03-Working/repo/` | The application repo (own git repo) |
| `03-Working/dep-probe/` | Verified dependency-resolution probe (throwaway) |
| `04-Reference/` | `formulas.md`, `extracted_images/` |

## Document set

**Authoritative (clean originals, v2.0.0):**
- `01-Received/quantumcrewbd_master_mvp_specification.md` — the build spec
- `01-Received/quantumcrewbd_product_requirements_document_prd.md` — the requirements authority

**Supporting (lossy text renditions, v1.0.0)** — usable, but 115 + 34 backslash-escape
artifacts and mangled base64 images. Do not trust character-level detail from these:
- `01-Received/QuantumCrewBD_Autonomous_Engineering_Design_Implementation_Plan_v1.0.0.md`
- `01-Received/QuantumCrewBD_Engineering_Implementation_Strategy_Execution_Plan_v1.0.0.md`

## Verified infrastructure (checked live 2026-10-03)

| Asset | Value |
|---|---|
| Supabase project | **QuantumCrewBD** — ref `qukqelcqngvlplayhjtp`, org `qepybclomycfpwxwjmzv` |
| Supabase region / engine | `ap-northeast-2`, PostgreSQL **17.11**, ACTIVE_HEALTHY |
| Supabase public schema | **0 tables** (unapplied) — 27 auth tables present |
| CrewAI platform | base `https://app.crewai.com/crewai_plus/api/v1`, PAT valid, workspace empty |
| LLM key | ✅ **Groq** supplied + validated — `openai/gpt-oss-120b` available |
| GitHub repo | **`mahmudaq/quantumcrewbd`** (private) — access = **write, NOT admin** |
| Runtime | Python 3.11 + 3.12 both present (3.14 excluded — crewai requires `<3.14`) |

All credentials are in **KeePassXC** under `/QuantumCrewBD/`:
`CrewAI-PAT`, `Supabase-PAT`, `Supabase-anon-key`, `Supabase-service_role-key`,
`Supabase-publishable-key`, `Groq-API-Key`.
Expiry dates **unknown — need confirming with the owner.**

**GitHub access boundary (verified by live push test, not assumed):**

| Capability | Status |
|---|---|
| Clone / read private repo | ✅ verified |
| Push commits + create/delete branches | ✅ verified |
| Open/merge PRs, manage issues (triage) | ✅ |
| Change repo visibility, delete repo | ❌ **admin required — owner only** |
| Manage collaborators, Actions secrets, branch protection | ❌ **admin required — owner only** |

## Locked technical decisions

1. **`crewai==1.15.23`, pinned exactly** (never a range — 1.x has broken its tool API repeatedly).
2. **Search layer is in-house** (`ddgs`) — `crewai-tools` ships **no** DuckDuckGo tool.
   Not installing `crewai-tools` at all (it hard-pins crewai and drags in unmaintained `pytube`).
3. **LLM via `crewai.LLM(provider="openai_compatible", base_url=…, api_key=…)`** —
   crewai 1.x has **no Groq provider and no litellm**. Env contract:
   `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME`. Keeps the backend swappable.
4. **`pydantic` must be `<2.13`** (crewai requires `>=2.11.9,<2.13` → resolves to 2.12.5).
5. **Supabase access is user-JWT-scoped, not anon.** Agent tools run server-side with no
   session, so under RLS `auth.uid() = NULL` returns **zero rows** — the internal-bench /
   TECH-6 feature would silently never fire. Build `get_user_client(access_token)`.
6. **Two concurrent single-agent crews** for Tracks A/B — native `async_execution` cannot
   express the two-parallel-track topology (at most one async task, and it must be last).
7. **`st.session_state` holds only JSON-serialisable data** — never CrewAI objects.

## Doc defects found (details in `02-Sent/…Plan_v1.0.0.md` §2)

| ID | Defect | Severity |
|---|---|---|
| R-01 | Doc `requirements.txt` fails to install (stale pins, pydantic conflict) | 🔴 |
| R-02 | `DuckDuckGoSearchTool` does not exist in crewai-tools 1.x | 🔴 |
| R-03 | `ChatGroq` / langchain-groq has no path in crewai 1.x | 🔴 |
| R-04 | Agent tools on the anon key get 0 rows under RLS → flagship feature never fires | 🔴 |
| R-05 | "Parallel tracks" not natively expressible | ⚠️ |
| R-06 | ≤90 s Phase-2 budget unproven | ⚠️ |
| R-07 | Streamlit Cloud 1-CPU ceiling | ⚠️ |
| R-08 | No sample tender corpus supplied | ⚠️ |
| R-09 | Unused tool args; package-name inconsistencies | ℹ️ |

## Open items needing Mahmud's decision

1. **Sample tenders** — real WB/ADB/PPRA packs (user is providing), else 3 synthetic fixtures.
2. **Hosting** — recommend this VPS + Docker + Tailscale Funnel over Streamlit Cloud.
3. **Branch protection on `main`** — currently **unprotected**. Worth enabling for a 4-person
   team, but note: once protected, this non-admin token can no longer push to `main` directly.
4. **Internal-vs-external bench scope** — the RLS/vacancy machinery implies an org-level
   `team_cvs` pool visible to all tenant users. Confirm that's intended before I build it.

### Resolved
- ✅ **LLM provider** — Groq key supplied + validated (`openai/gpt-oss-120b`). CommandCodeAI can
  be swapped in later; the `openai_compatible` abstraction makes it a 3-env-var change.
- ✅ **GitHub repo** — `mahmudaq/quantumcrewbd`; pending invitation accepted, write access
  verified by real push. **Not admin** — owner must handle visibility/settings/collaborators.

## Useful capabilities discovered

- **Supabase Management API runs arbitrary SQL:**
  `POST https://api.supabase.com/v1/projects/{ref}/database/query {"query": "..."}` → 201.
  Lets us apply `schema.sql` and verify RLS **without the DB password**.
  `GET /v1/projects/{ref}/api-keys` retrieves anon/service_role keys.
- **CrewAI PAT host gotcha:** it authenticates `app.crewai.com`, **not** `api.crewai.com`
  (that's the separate deployment/"Ferry" service needing an `x-internal-api-key` header).
  PAT env var name inside crewai is `CREWAI_USER_PAT`.

## Change log

- 2026-10-03 — Project scaffolded; 4 documents received; E2E development plan v1.0.0 delivered.
- 2026-10-03 — Credentials (CrewAI PAT, Supabase PAT, 3 Supabase keys) validated and stored in KeePassXC.
