# QuantumCrewBD — Master Minimum Viable Product (MVP) Specification

**Document Version:** 2.0.0

**Project Name:** **QuantumCrewBD**

**Hackathon Event:** HEC PakAngels Aspire Hackathon 2 (Cohort 11)

**Strategic Lead & Visionary:** Dr. Irfan Ahmed Khan

**Project Lead:** Mahmud Qureshi

**Core Engineering Team:** Ali Uddin Khan, Durre Nayab, Saad Saeed

**Target Runtime:** Python 3.11 / 3.12 (Strict dependency lock for CrewAI stability)

**Core Frameworks & Cloud Services:** CrewAI, Streamlit 1.38+, Supabase (Auth + PostgreSQL + RLS), Groq (`openai/gpt-oss-120b`), DuckDuckGo Search (`duckduckgo-search`)

## 1. Executive Summary & Problem Definition

### 1.1 The Procurement Friction Landscape

Small-to-midsize tech enterprises, IT consultancies, and digital agencies forfeit high-value public tenders, bilateral funding grants, and enterprise Requests for Proposals (RFPs) not because of engineering inability, but due to procurement overhead:

1. **Gatekeeper Disqualification & Complex Frameworks:** Multilateral funding institutions (e.g., World Bank, Asian Development Bank, UN) and government authorities (e.g., PPRA) enforce rigid Standard Procurement Documents (SPDs) and binary qualification gates. Overlooking mandatory tax clearances, turnover minimums, joint-and-several liability clauses, or standard form conventions results in immediate rejection prior to technical scoring.

2. **Standardized CV & Bio-data Formatting Traps:** Donors reject proposals containing generic corporate or LinkedIn-style CVs. They mandate strict biodata structures (e.g., World Bank Form `TECH-6`) with explicit task-to-experience adequacy mapping.

3. **Consortium & Joint Venture (JV) Deficits:** Over 60% of tenders require teaming agreements to satisfy missing corporate accreditations (ISO 27001, CMMI Level 3/5) or turnover minimums. Teams lack mechanisms to rapidly identify internal and external teaming partners.

4. **Suboptimal Talent Bench Querying:** Capture teams spend days manually searching disconnected resumes, guessing market billing day-rates, and miscalculating Full-Time Equivalent (FTE) labor distributions across project milestones.

5. **Lack of Red-Team Compliance Auditing:** Rushed submissions lack adversarial verification against evaluation rubrics across Evidence, Accuracy, Completeness, and Quality.

### 1.2 The Solution: QuantumCrewBD

**QuantumCrewBD** is an enterprise-grade multi-agent procurement intelligence and proposal synthesis platform. Built on CrewAI's Business Process Automation (BPA) pattern and running on Streamlit with Supabase persistence, it deploys a 5-agent sequential pipeline governed by a **Pattern 1 Stage-Gated Human-in-the-Loop (HITL) Checkpoint**.

QuantumCrewBD extracts tender criteria, validates regulatory frameworks, optimizes internal and external talent pools into donor-compliant Form `TECH-6` resumes, discovers corporate consortium partners, drafts submission-ready technical bids, and performs red-team compliance QA scoring before submission.

## 2. High-Level System Architecture & Flow

```
                                 ┌──────────────────────────────────┐
                                 │     User Client (Web Browser)    │
                                 └─────────────────┬────────────────┘
                                                   │
                                                   ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 STREAMLIT APPLICATION (QuantumCrewBD)                                  │
│                                                                                                        │
│   [Auth Gateway] ──► [Talent Bench] ──► [Consortium Directory] ──► [Bid Studio & Mission Control]     │
└───────────────┬───────────────────────────────────────────────────────────────┬────────────────────────┘
                │ 1. Auth & Isolated CRUD                                       │ 2. Pipeline Execution
                ▼                                                               ▼
┌────────────────────────────────────────┐                    ┌──────────────────────────────────────────┐
│      SUPABASE MANAGED CLOUD DB         │                    │     STAGE-GATED CREWAI PIPELINE          │
│                                        │                    │                                          │
│ • Supabase Auth (JWT / Sessions)       │                    │ [ Phase 1: Ingestion & Deconstruction ]  │
│ • PostgreSQL Database with RLS:        │                    │   Agent 1: RFP & Compliance Specialist   │
│   - `profiles`                         │                    │              │                           │
│   - `team_cvs` (Talent Pool)           │◄────── Query ──────┤              ▼                           │
│   - `consortium_partners` (JV Bench)   │◄────── Query ──────┤ 🛑 STREAMLIT HITL CHECKPOINT            │
│   - `proposals` (Saved Dossiers)       │                    │   • Verify Donor Framework (WB/ADB/PPRA) │
│                                        │                    │   • Review Staffing Mandates & Upload CV │
│                                        │                    │   • Explicit Human Authorization Click   │
│                                        │                    │              │                           │
│                                        │                    │ [ Phase 2: Synthesis, Resourcing & QA ]  │
│                                        │                    │   ├─► Agent 2: Market Intel Analyst      │
│                                        │                    │   └─► Agent 3: Resource & JV Planner     │
│                                        │                    │              │                           │
│                                        │                    │              ▼                           │
│                                        │                    │       Agent 4: Technical Proposal Writer │
│                                        │                    │              │                           │
│                                        │                    │              ▼                           │
│                                        │                    │       Agent 5: Compliance QA Auditor     │
│                                        │                    └──────────────────────┬───────────────────┘
│                                        │                                           │
└────────────────────────────────────────┘                                           │
                    ▲                                                                │
                    └──────────────────── Persist Audited Dossier ───────────────────┘

```

## 3. Database Architecture & Row-Level Security (Supabase DDL)

To enforce strict multi-tenant isolation, the database utilizes four relational tables in PostgreSQL. Row-Level Security (RLS) policies mandate that authenticated users can only query, insert, update, and delete their own organization's records.

### 3.1 Production Migration Script (`database/schema.sql`)

```
-- ============================================================================
-- 1. PROFILES TABLE (User Accounts & Tenant Metadata)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    organization_name TEXT DEFAULT 'Quantum Enterprise',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own profile"
ON public.profiles FOR ALL
TO authenticated
USING (auth.uid() = id)
WITH CHECK (auth.uid() = id);

-- Trigger to automatically create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$ BEGIN     INSERT INTO public.profiles (id, email, organization_name)     VALUES (new.id, new.email, 'Quantum Enterprise');     RETURN NEW; END; $$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ============================================================================
-- 2. TEAM CVS TABLE (Internal Talent Bench)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.team_cvs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    current_role TEXT NOT NULL,
    years_experience INT NOT NULL DEFAULT 0,
    education TEXT,                        -- e.g. 'M.S. in Computer Science, Stanford'
    certifications TEXT[] DEFAULT '{}',    -- e.g. ['CISSP', 'PMP', 'AWS Solutions Architect']
    clearance_level TEXT DEFAULT 'None',   -- e.g. 'None', 'Public Trust', 'Secret', 'Top Secret'
    skills TEXT[] DEFAULT '{}',            -- e.g. ['Kubernetes', 'Python', 'ISO 27001 Auditing']
    languages JSONB DEFAULT '{"English": "Excellent"}'::jsonb,
    cv_summary TEXT NOT NULL,
    past_performance_refs TEXT,            -- Past projects mapped to TOR tasks
    hourly_rate NUMERIC DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.team_cvs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own talent bench"
ON public.team_cvs FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_team_cvs_user ON public.team_cvs(user_id);
CREATE INDEX IF NOT EXISTS idx_team_cvs_role ON public.team_cvs(current_role);

-- ============================================================================
-- 3. CONSORTIUM PARTNERS TABLE (Vetted Teaming & Joint Venture Directory)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.consortium_partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    primary_domain TEXT NOT NULL,          -- e.g. 'Cloud Security', 'Civil Engineering', 'Fintech'
    specialties TEXT[] DEFAULT '{}',       -- e.g. ['AWS GovCloud', 'FedRAMP Compliance']
    certifications TEXT[] DEFAULT '{}',   -- e.g. ['ISO 27001', 'CMMI Level 3', 'ISO 9001']
    annual_turnover_tier TEXT,            -- e.g. '$1M-$5M', '$5M-$20M', '$20M+'
    key_past_performance TEXT NOT NULL,   -- Major enterprise/public contracts delivered
    point_of_contact_name TEXT,
    point_of_contact_email TEXT,
    website TEXT,
    vetting_status TEXT DEFAULT 'Vetted', -- 'Vetted', 'Past Lead', 'Prospect'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.consortium_partners ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own consortium directory"
ON public.consortium_partners FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_consortium_user ON public.consortium_partners(user_id);
CREATE INDEX IF NOT EXISTS idx_consortium_domain ON public.consortium_partners(primary_domain);

-- ============================================================================
-- 4. PROPOSALS TABLE (Audited Dossiers & Bid Runs)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    project_title TEXT NOT NULL,
    client_name TEXT DEFAULT 'Public / Enterprise Tender',
    governing_framework TEXT DEFAULT 'World Bank SPD',
    raw_rfp_text TEXT NOT NULL,
    compliance_score INT DEFAULT 0,
    generated_proposal TEXT NOT NULL,
    audit_feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.proposals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own proposals"
ON public.proposals FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_proposals_user ON public.proposals(user_id);

```

## 4. Multi-Agent Pipeline & Stage-Gated Workflow

### 4.1 Phase 1 vs. Phase 2 Execution Breakdown

Under **Pattern 1 (Stage-Gated Execution)**, execution halts cleanly between Phase 1 and Phase 2, eliminating browser thread-locking while giving the user full governance over donor standards and candidate sourcing.

```
[ Phase 1: Ingestion & Regulatory Deconstruction ]
                        │
                        ▼
             Agent 1: RFP Analyzer
                        │
                        ▼ Output: Scope, Mandates & Detected Donor Framework
═══════════════════════════════════════════════════════════════════════════════════════════
 🛑 STREAMLIT HITL CHECKPOINT (Human Review & Guideline Confirmation)
 
 1. Multilateral / Institutional Guideline Review:
    • Displays detected procurement framework (World Bank SPD, ADB QCBS, PPRA SBD, Commercial).
    • Identifies mandatory standard submission forms (e.g., TECH-1 through TECH-6).
    • Flags formatting rules (page budgets, font constraints, binding requirements).
    • User confirms or overrides the guideline profile.

 2. Personnel & Consortium Verification:
    • Reviews mandatory key roles, years of experience, and ISO/CMMI prerequisites.
    • Verifies internal bench matches or uploads missing candidate CVs / partner profiles.
    
 3. Explicit User Authorization:
    • User clicks [ 🚀 Confirm Guidelines & Proceed to Proposal Synthesis ].
═══════════════════════════════════════════════════════════════════════════════════════════
                        │ Input: Confirmed Framework + Staffing Directives + Injected CVs
                        ▼
[ Phase 2: Intelligence, Resourcing, Drafting & Audit ]
   ┌────────────────────────────────────────────────────────────┐
   │ Parallel Intelligence & Sourcing Track                     │
   │  ├─► Agent 2: Market Intel Analyst                         │
   │  └─► Agent 3: Resource & Consortium Planner                │
   │       (Transforms raw CVs into Donor Form TECH-6 format)   │
   └─────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
                   Agent 4: Lead Technical Writer
                   (Drafts strictly to confirmed Donor Standard Forms)
                                 │
                                 ▼
                   Agent 5: Compliance QA Auditor
                   (Adversarial audit against Donor Guidelines & Pass/Fail Rules)
                                 │
                                 ▼
            [ Persist Audited Dossier to Supabase `proposals` ]

```

### 4.2 Detailed Agent Responsibilities & Contracts

#### Agent 1: RFP & Compliance Deconstruction Specialist

* **Module:** `agents/analyzer.py`

* **Role:** Senior Procurement & Compliance Specialist

* **Goal:** Thoroughly analyze raw tender documents to extract mandatory pass/fail criteria, technical deliverables, evaluation rubrics, key personnel mandates, consortium prerequisites, and detect the governing procurement framework.

* **Input:** `raw_rfp_text`, `project_title`, `client_name`

* **Active Responsibilities:**

  1. Detects governing procurement framework (e.g., World Bank SPD, ADB QCBS, PPRA SBD, or Custom Commercial).

  2. Identifies required standard submission forms (e.g., Forms `TECH-1` to `TECH-6`, `FIN-1` to `FIN-4`).

  3. Extracts gatekeeper clauses (financial turnover thresholds, security clearances, bid security requirements).

  4. Isolates key personnel mandates (roles, minimum experience, mandatory vendor certifications, degrees).

  5. Extracts consortium and teaming mandates (mandatory ISO 27001, CMMI, joint venture liability rules).

* **Output Artifact (Triggers the HITL Checkpoint):** `RFPComplianceDossier` containing `detected_framework`, `mandatory_forms`, `compliance_matrix`, `personnel_mandates`, and `teaming_mandates`.

#### Agent 2: Market & Competitor Intelligence Analyst

* **Module:** `agents/market_intel.py`

* **Role:** Competitive Intelligence & Industry Benchmarking Analyst

* **Goal:** Gather external benchmark pricing, prevailing vendor day-rates, technical standards, and domain-specific case references to ground the commercial and architectural sections.

* **Tools:** `DuckDuckGoSearchTool`

* **Input:** Output from Agent 1 (SOW, target jurisdiction, technology domain).

* **Active Responsibilities:**

  1. Conducts web searches to benchmark market day-rates for required roles in the target jurisdiction.

  2. Retrieves prevailing technical standards, digital public infrastructure (DPI) guidelines, and open standards.

  3. Synthesizes competitor positioning angles and high-impact value-add differentiators.

* **Output Artifact:** `MarketIntelligenceDossier` containing regional rate benchmarks, architectural standards, and win themes.

#### Agent 3: Resource & Consortium Planner

* **Module:** `agents/resource_planner.py`

* **Role:** Principal Resource Allocator & Strategic Teaming Director

* **Goal:** Reconcile technical requirements with internal personnel benches, corporate partner directories, and live external sourcing to build a verified Key Personnel Roster, Consortium Teaming Structure, and **format candidate resumes strictly into the confirmed donor biodata standard (Form TECH-6)**.

* **Tools:**

  * `internal_cv_search`: Queries Supabase `team_cvs`.

  * `internal_partner_search`: Queries Supabase `consortium_partners`.

  * `external_talent_discovery`: DuckDuckGo Boolean search (`site:linkedin.com/in/`, `site:indeed.com/r/`).

  * `external_partner_discovery`: DuckDuckGo B2B search (`site:clutch.co`, corporate directories).

* **Active Responsibilities:**

  1. Matches internal bench members in `team_cvs` against mandatory roles, certifications, and years of experience.

  2. Queries `consortium_partners` to cover mandatory corporate certifications (ISO 27001, CMMI) or turnover minimums.

  3. Executes external talent and partner discovery if internal benches leave gaps.

  4. **Donor CV Transformation Engine:** Systematic restructuring of raw CV data into the exact 8-part biodata structure mandated by World Bank / ADB Form `TECH-6`.

  5. **Assignment Adequacy Mapping:** Cross-references the RFP's specific Terms of Reference (TOR) deliverables with past projects completed by the expert.

  6. **Level of Effort Allocation:** Calculates labor distribution across project milestones:
     

     $$
     \text{Total Mandays} = \sum (\text{Phase Duration (Days)} \times \text{FTE Allocation})
     $$

* **Output Artifact:** `ResourceAndConsortiumDossier` containing `KeyPersonnelTable`, `FormattedDonorCVs` (Form `TECH-6`), `ConsortiumStructure` (teaming splits), and `LevelOfEffortTable`.

#### Agent 4: Lead Technical Proposal Architect

* **Module:** `agents/writer.py`

* **Role:** Principal Technical Bid Writer & Solution Architect

* **Goal:** Synthesize the parsed RFP criteria, market intelligence, resource allocation plan, consortium teaming structure, and formatted donor CVs into a persuasive proposal drafted **strictly according to the confirmed donor guidelines and standard forms**.

* **Input:** Unified outputs from Agents 1, 2, and 3 + Confirmed Guidelines from HITL Checkpoint.

* **Active Responsibilities:**

  1. Structures narrative strictly into confirmed standard forms:

     * **If World Bank / ADB QCBS Confirmed:**

       * `Form TECH-1`: Letter of Technical Proposal Submission.

       * `Form TECH-2`: Consultant’s Organization, Experience, and Consortium Partner Profiles.

       * `Form TECH-3`: Comments and Suggestions on the Terms of Reference (TOR).

       * `Form TECH-4`: Description of Approach, Methodology, Work Plan, and Organization.

       * `Form TECH-5`: Work Schedule and Planning for Deliverables.

       * `Form TECH-6`: Team Composition, Assignment, and Formatted Personnel CVs.

     * **If Commercial Standard Confirmed:** Executive Summary, Technical Architecture, WBS, Governance, Commercials, and Risk Management.

  2. Articulates the technical solution architecture and implementation methodology.

  3. Documents prime vs. subcontractor teaming splits and joint liabilities.

* **Output Artifact:** `DraftProposalDossier` formatted in complete, structured Markdown.

#### Agent 5: Executive Compliance & QA Auditor

* **Module:** `agents/reviewer.py`

* **Role:** Executive Bid Auditor & Quality Controller

* **Goal:** Perform an adversarial red-team audit of the draft proposal against the original RFP requirements and the confirmed institutional guidelines across the four evaluation dimensions: Evidence, Accuracy, Completeness, and Quality.

* **Input:** Draft Proposal Dossier (from Agent 4) + Original Raw RFP Text + Confirmed Guidelines.

* **Active Responsibilities:**

  1. **CV Compliance & Integrity Audit:** Validates that 100% of candidate CVs conform to Form `TECH-6`, confirming that experience dates substantiate minimum years required and that the statutory certification clause is present.

  2. **4-Dimension Verification:**

     * **Evidence:** Verifies that all technical claims and qualifications are substantiated by concrete references.

     * **Accuracy:** Detects hallucinations, unrealistic timelines, or mathematical discrepancies in FTE tables.

     * **Completeness:** Ensures 100% coverage of mandatory requirements and standard forms (`TECH-1` to `TECH-6`).

     * **Quality & Guideline Adherence:** Verifies compliance with donor-specific page limitations, formatting rules, and submission constraints.

  3. Computes the composite compliance score:
     

     $$
     \text{Compliance Score} = \left( \frac{\text{Passed Mandatory Items}}{\text{Total Mandatory Items}} \right) \times 100\%
     $$

  4. Directly polishes detected defects, producing the final, submission-ready proposal dossier.

* **Output Artifact:** `FinalSubmissionDossier` containing `ComplianceScorecard` (0–100%), `AuditFindingsReport`, and `FinalProposalText`.

## 5. Standardized Donor CV Transformation Engine (Form TECH-6)

One of the primary causes of tender disqualification in multilateral procurement is submitting resumes in standard corporate formats. QuantumCrewBD embeds an automated transformation pipeline:

```
[ Raw Candidate CV ] (PDF / Text / LinkedIn Profile / Supabase Bench)
                            │
                            ▼
           [ Agent 3: CV Transformation Engine ]
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│           WORLD BANK / ADB STANDARD BIODATA FORMAT (FORM TECH-6)       │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Position Title and Assigned Role Number (e.g. Key Expert 1 [K-1])   │
│ 2. Personal Information (Full legal name, DOB, nationality, residence) │
│ 3. Formal Education (Degrees, institutions, graduation dates)          │
│ 4. Professional Accreditations & Licenses (PMP, CISSP, PEC, etc.)      │
│ 5. Language Proficiency Matrix (Speaking / Reading / Writing ratings)  │
│ 6. Chronological Employment Record (Preceding 10-15 years)             │
│ 7. Adequacy for the Assignment (Assignment Mapping Matrix):            │
│    • Mandatory TOR Tasks Assigned                                      │
│    • Past Work Undertaken that Best Illustrates Capability             │
│ 8. Statutory Certification & Attestation Legal Block                   │
└────────────────────────────────────────────────────────────────────────┘

```

## 6. Execution View & Mission Control UI Specification

To give users and hackathon judges total visibility into multi-agent operations without cluttering the interface, the Execution View provides a two-tier presentation model:

### 6.1 Inline Tickers & Two-Column Topology

* **Stream A (Market Intel Analyst):** Displays web search queries, rate benchmarks, and domain standards.

* **Stream B (Resource & Consortium Planner):** Displays Supabase queries against `team_cvs` and `consortium_partners`, live external talent sourcing, and Form `TECH-6` formatting.

* **Inline Processing Tickers:** Each card contains a real-time `Current Activity:` micro-ticker updating dynamically via CrewAI step callbacks.

### 6.2 Granular ReAct Trace Tabs

An expandable drawer beneath the pipeline cards contains segmented tabs for each agent (`[📋 Analyzer]`, `[🌐 Market Intel]`, `[👥 Resource & JV]`, `[✍️ Writer]`, `[⚖️ Auditor]`), exposing the exact ReAct loop:

$$
\text{Thought} \longrightarrow \text{Action (Tool Call + Arguments)} \longrightarrow \text{Observation}
$$

## 7. Custom Tools Implementation (`tools.py`)

```
"""
Custom Tool Definitions for QuantumCrewBD.
Implements internal Supabase queries and external web discovery
for both talent candidates and corporate consortium partners.
"""
from crewai.tools import tool
from crewai_tools import DuckDuckGoSearchTool
from database.supabase_client import get_supabase_client

# 1. Base Web Search Tool
web_search_tool = DuckDuckGoSearchTool()

# 2. Internal Talent Bench Search Tool
@tool("Internal CV Talent Search")
def internal_cv_search(query: str, min_years: int = 0) -> str:
    """
    Searches the internal organization CV database in Supabase for matching
    roles, certifications, and skills. Use this tool before searching externally.
    """
    supabase = get_supabase_client()
    try:
        response = supabase.table("team_cvs").select("*").gte("years_experience", min_years).execute()
        records = response.data
        if not records:
            return "No matching internal candidates found in the company bench."
        
        results = []
        for r in records:
            results.append(
                f"- Name: {r['full_name']} | Role: {r['current_role']} | "
                f"Exp: {r['years_experience']} yrs | Education: {r.get('education', 'N/A')} | "
                f"Certs: {', '.join(r.get('certifications', []))} | Rate: ${r.get('hourly_rate', 0)}/hr\n"
                f"  Summary: {r['cv_summary']}\n  Past Projects: {r.get('past_performance_refs', 'N/A')}"
            )
        return "\n".join(results)
    except Exception as e:
        return f"Error querying internal talent bench: {str(e)}"

# 3. Internal Consortium Partner Search Tool
@tool("Internal Consortium Partner Search")
def internal_partner_search(domain_or_cert: str) -> str:
    """
    Searches the internal database of vetted consortium partners and subcontractors
    in Supabase to satisfy corporate certifications (ISO 27001, CMMI),
    turnover criteria, or specialized domain expertise.
    """
    supabase = get_supabase_client()
    try:
        response = supabase.table("consortium_partners").select("*").execute()
        records = response.data
        if not records:
            return "No existing consortium partners found in the internal directory."
        
        results = []
        for r in records:
            results.append(
                f"- Company: {r['company_name']} | Domain: {r['primary_domain']} | "
                f"Certs: {', '.join(r.get('certifications', []))} | Turnover: {r.get('annual_turnover_tier', 'N/A')} | "
                f"Status: {r.get('vetting_status', 'Vetted')}\n  Past Performance: {r['key_past_performance']}"
            )
        return "\n".join(results)
    except Exception as e:
        return f"Error querying consortium partners: {str(e)}"

# 4. External Talent Discovery Tool
@tool("External Talent Discovery Tool")
def external_talent_discovery(role_title: str, required_cert: str = "", location: str = "") -> str:
    """
    Performs targeted web searches across professional directories to find
    external candidate benchmarks, qualifications, and billing rates.
    """
    search = DuckDuckGoSearchTool()
    search_query = f'site:linkedin.com/in/ "{role_title}" "{required_cert}" {location}'
    results = search.run(search_query)
    if not results or "no results" in results.lower():
        fallback_query = f"average day rate salary requirements for {role_title} {required_cert}"
        results = search.run(fallback_query)
    return results

# 5. External Consortium & Partner Discovery Tool
@tool("External Partner Discovery Tool")
def external_partner_discovery(required_domain: str, required_cert: str = "") -> str:
    """
    Performs targeted web searches across B2B trade directories (Clutch, specialized portals)
    to discover corporate joint venture or subcontractor partners holding specific certifications.
    """
    search = DuckDuckGoSearchTool()
    search_query = f'site:clutch.co "{required_domain}" "{required_cert}" IT services partner'
    results = search.run(search_query)
    if not results or "no results" in results.lower():
        fallback_query = f"top certified IT enterprise consulting firms {required_domain} {required_cert}"
        results = search.run(fallback_query)
    return results

```

## 8. Streamlit Frontend Architecture (`app.py`)

### 8.1 4-Tab Workspace Layout

The application provides an authenticated workspace divided into four tabs:

1. **Tab 1: Bid Studio (`/studio`)**

   * **Stage 1 (Ingestion):** Project Title, Client Name, Submission Deadline, and Raw RFP Text (or `.txt`/`.pdf` upload).

   * **Stage 2 (HITL Checkpoint Cockpit):**

     * Section A: Multilateral Guideline Governance (World Bank SPD, ADB QCBS, PPRA SBD, Commercial) with standard forms list. Human confirm/override.

     * Section B: Personnel & Consortium Verification (view extracted mandates, upload missing CVs directly to `team_cvs`, set subcontractor partner preferences).

     * Action: **"🚀 Confirm Guidelines & Proceed to Proposal Synthesis"** button.

   * **Stage 3 (Mission Control & Synthesis):** Real-time `CollaborationMonitor` execution view with parallel tracks, active tickers, and collapsible ReAct trace tabs.

   * **Stage 4 (Audited Bid Review):** Metric Card displaying Compliance Score (0–100%), markdown dossier viewer, and one-click `.md` and `.txt` export buttons.

2. **Tab 2: Talent Bench Manager (`/bench`)**

   * Profile registration form to insert team members into `team_cvs` (Full Name, Role, Years Exp, Education, Certifications, Clearance, Hourly Rate, Summary, Past Projects).

   * Filterable table view of active personnel.

3. **Tab 3: Consortium & Partner Directory (`/partners`)**

   * Partner registration form to insert teaming partners into `consortium_partners` (Company Name, Domain, Specialties, Certifications, Turnover Tier, Past Performance, POC Email).

   * Filterable table of vetted corporate partners.

4. **Tab 4: Proposal Archive (`/history`)**

   * Instant lookup of all audited proposals saved under the user's `auth.uid()`, eliminating redundant LLM token costs.

## 9. Environment Configuration & Runtime Dependencies

### 9.1 Runtime Constraints

* **Python Runtime:** Python **3.11** or **3.12** (Mandatory: Python 3.14 is incompatible with current CrewAI dependencies).

* **LLM Engine:** Groq via `openai/gpt-oss-120b` or LiteLLM wrapper.

### 9.2 Streamlit Secrets Configuration (`.streamlit/secrets.toml`)

```
# LLM Inference
GROQ_API_KEY = "gsk_..."
OPENAI_MODEL_NAME = "openai/gpt-oss-120b"

# Supabase Platform
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "eyJhbGciOi..."  # Use public anon key (RLS enforced)

```

### 9.3 Locked Dependency Specifications (`requirements.txt`)

```
crewai>=0.80.0
crewai-tools>=0.14.0
streamlit>=1.38.0
supabase>=2.8.0
langchain-groq>=0.2.0
duckduckgo-search>=6.3.0
pydantic>=2.8.0
python-dotenv>=1.0.1

```

## 10. File & Directory Inventory

```
quantumcrew_bd/
├── .streamlit/
│   ├── config.toml                  # Streamlit theme and layout configuration
│   └── secrets.toml                 # API credentials & Supabase URL/Key
├── database/
│   ├── __init__.py
│   ├── schema.sql                   # Supabase schema with team_cvs, consortium, RLS
│   └── supabase_client.py           # Supabase connection & Auth session helpers
├── agents/
│   ├── __init__.py
│   ├── analyzer.py                  # Agent 1: RFP & Compliance Specialist (WB/ADB detection)
│   ├── market_intel.py              # Agent 2: Market & Competitor Intelligence Analyst
│   ├── resource_planner.py          # Agent 3: Resource & Consortium Planner (TECH-6 Engine)
│   ├── writer.py                    # Agent 4: Lead Technical Proposal Architect
│   └── reviewer.py                  # Agent 5: Executive Compliance & QA Auditor
├── ui/
│   ├── __init__.py
│   └── collaboration_board.py       # Compact Real-time Execution Monitor Component
├── tools.py                         # Custom tools: internal CV/partner + web talent/partner
├── crew.py                          # Phase 1 & Phase 2 CrewAI pipeline orchestration
├── app.py                           # Streamlit UI (Auth, HITL Checkpoint, Bench, Studio)
├── requirements.txt                 # Pinned Python dependencies
└── README.md                        # Hackathon Pitch & Quickstart Guide

```

## 11. Hackathon Delivery Roadmap

| **Milestone** | **Deliverables** | **Target Duration** | 
| **Stage 1: DB & Auth Provisioning** | Execute `database/schema.sql` on Supabase, configure `secrets.toml`, and initialize `database/supabase_client.py`. | 30 Mins | 
| **Stage 2: Tooling & Agent Contracts** | Implement `tools.py` (internal/external searches) and the 5 agent modules in `agents/`. | 45 Mins | 
| **Stage 3: Stage-Gated Pipeline (`crew.py`)** | Implement two-phase execution functions (`run_analyzer_phase` and `run_proposal_generation_phase`). | 30 Mins | 
| **Stage 4: Streamlit Frontend & HITL Cockpit** | Build `app.py` with Auth gateway, Talent Bench manager, Consortium manager, and Pattern 1 Checkpoint UI. | 60 Mins | 
| **Stage 5: Verification & Demo Recording** | Run end-to-end tender test (World Bank SPD sample), verify RLS isolation across 2 user accounts, and record live pitch demo. | 45 Mins | 
