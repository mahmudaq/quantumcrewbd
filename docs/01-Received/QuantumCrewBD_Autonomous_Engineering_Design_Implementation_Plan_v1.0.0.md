# **QuantumCrewBD — Autonomous Engineering Design & Implementation Plan**

**Document Version:** 1.0.0

**Target Runtime:** Python 3.11 / 3.12 (Strict CrewAI runtime compatibility)

**Primary Stack:** CrewAI, Streamlit 1.38+, Supabase (PostgreSQL \+ Auth \+ RLS), Groq (openai/gpt-oss-120b), DuckDuckGo Search

**Target Audience:** Autonomous Development Agent & Core Engineering Team

**Governing References:** docs/PRD.md, docs/MVP\_SPECIFICATION.md, docs/AGENT\_RESPONSIBILITIES\_SPEC.md, docs/EXECUTION\_VIEW\_SPEC.md, docs/HITL\_HUMAN\_INPUT\_GUIDE.md

## **1\. Executive Directive & Development Mission**

### **1.1 Objective**

Build, verify, and package **QuantumCrewBD**, an enterprise-grade multi-agent procurement intelligence SaaS platform. The system ingests public and enterprise tender documents (specifically multilateral donors like World Bank, ADB, and PPRA), enforces standard procurement forms (TECH-1 through TECH-6), transforms raw talent resumes into standard biodata formats, discovers corporate joint-venture partners to satisfy mandatory gatekeeper accreditations (ISO 27001, CMMI), and conducts an adversarial 4-dimension compliance audit (Evidence, Accuracy, Completeness, Quality).

### **1.2 Non-Negotiable Operational Constraints**

1. **Python Runtime Locking:** The runtime environment **must be strictly Python 3.11 or 3.12**. Python 3.14 breaks CrewAI dependency trees and must not be used.  
2. **Pattern 1 Stage-Gated HITL Architecture:** The multi-agent workflow is decoupled into two sequential phases separated by a Streamlit UI approval checkpoint. **Never invoke human\_input=True inside a native CrewAI task**, as it triggers blocking terminal input() and locks the Streamlit web worker.  
3. **Multi-Tenant Data Isolation (RLS):** All database operations against Supabase must execute under the active user's JWT or authenticated context (auth.uid() \= user\_id). Never bypass RLS in client workflows.  
4. **Donor Form Rigor:** Proposals must adhere to standard form structures (World Bank / ADB TECH-1 to TECH-6) and transform candidate CVs into the mandatory 8-part biodata format.

## **2\. Target File Tree & Module Responsibility Matrix**

The development agent must construct the codebase strictly adhering to the following directory structure:

quantumcrew\_bd/  
├── .streamlit/  
│   ├── config.toml                  \# UI theme, layout, dark-mode settings  
│   └── secrets.toml                 \# API keys (Groq, Supabase URL, Anon Key)  
├── database/  
│   ├── \_\_init\_\_.py  
│   ├── schema.sql                   \# Full PostgreSQL DDL \+ RLS \+ Triggers  
│   └── supabase\_client.py           \# Supabase client singleton & auth/session wrappers  
├── agents/  
│   ├── \_\_init\_\_.py  
│   ├── analyzer.py                  \# Agent 1: Senior Procurement & Compliance Specialist  
│   ├── market\_intel.py              \# Agent 2: Market & Competitor Intelligence Analyst  
│   ├── resource\_planner.py          \# Agent 3: Resource & Consortium Planner (TECH-6 CVs)  
│   ├── writer.py                    \# Agent 4: Lead Technical Proposal Architect  
│   └── reviewer.py                  \# Agent 5: Executive Compliance & QA Auditor  
├── ui/  
│   ├── \_\_init\_\_.py  
│   └── collaboration\_board.py       \# Live Execution Monitor & ReAct Trace Tabs  
├── tools.py                         \# Supabase CV/Partner search \+ DuckDuckGo search tools  
├── crew.py                          \# Phase 1 & Phase 2 CrewAI kickoff orchestrations  
├── app.py                           \# Multi-page tabbed Streamlit frontend with HITL gate  
├── requirements.txt                 \# Pinned Python package dependencies  
└── README.md                        \# Quickstart, setup runbook, and pitch architecture

## **3\. Phase-by-Phase Development Specification**

┌─────────────────────────────────────────────────────────────────────────────────┐  
│                          5-PHASE IMPLEMENTATION TIMELINE                        │  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 1: Environment, Dependencies & Cloud Persistence                          │  
│ Phase 2: Internal Bench & External Sourcing Tool Suite                          │  
│ Phase 3: The 5 Discrete Agent & Task Modules                                    │  
│ Phase 4: Stage-Gated Pipeline Orchestration & Callback Bridge                   │  
│ Phase 5: Streamlit Mission Control Frontend & HITL Cockpit                      │  
└─────────────────────────────────────────────────────────────────────────────────┘

### **Phase 1: Environment, Dependencies & Cloud Persistence**

#### **Deliverable 1.1: Dependency Specifications (requirements.txt)**

Create requirements.txt with locked versions:

crewai\>=0.80.0  
crewai-tools\>=0.14.0  
streamlit\>=1.38.0  
supabase\>=2.8.0  
langchain-groq\>=0.2.0  
duckduckgo-search\>=6.3.0  
pydantic\>=2.8.0  
python-dotenv\>=1.0.1

#### **Deliverable 1.2: PostgreSQL Schema with RLS (database/schema.sql)**

The dev agent must implement:

1. public.profiles: Links to auth.users(id) with auto-create trigger handle\_new\_user().  
2. public.team\_cvs: Candidate CV bank with columns for full\_name, current\_role, years\_experience, education, certifications (array), clearance\_level, skills (array), languages (jsonb), cv\_summary, past\_performance\_refs, and hourly\_rate.  
3. public.consortium\_partners: Vetted partners directory with company\_name, primary\_domain, specialties (array), certifications (array), annual\_turnover\_tier, key\_past\_performance, point\_of\_contact\_name, point\_of\_contact\_email, and vetting\_status.  
4. public.proposals: Generated dossiers with user\_id, project\_title, client\_name, governing\_framework, raw\_rfp\_text, compliance\_score, generated\_proposal, and audit\_feedback.  
5. RLS policies on all four tables restricting SELECT, INSERT, UPDATE, and DELETE strictly to (auth.uid() \= user\_id).

#### **Deliverable 1.3: Supabase Client Factory (database/supabase\_client.py)**

Implement helper functions:

* get\_supabase\_client(): Reads SUPABASE\_URL and SUPABASE\_KEY from st.secrets or os.environ.  
* sign\_up\_user(email, password): Supabase auth registration.  
* sign\_in\_user(email, password): Supabase auth login returning user session token.  
* fetch\_talent\_bench(user\_id): Fetches team records.  
* fetch\_consortium\_partners(user\_id): Fetches partner records.  
* save\_proposal\_record(proposal\_data): Inserts audited proposal.

**Verification Gate 1:** Verify script execution against Supabase SQL editor; confirm anonymous requests without user JWT fail RLS evaluation.

### **Phase 2: Sourcing & Search Tool Suite (tools.py)**

The dev agent must construct four custom CrewAI tools using the @tool decorator:

1. **internal\_cv\_search(query: str, min\_years: int \= 0\) \-\> str**:  
   * Queries Supabase team\_cvs filtering by minimum years of experience and keyword matching on role and certifications.  
   * Returns formatted markdown blocks containing name, role, certifications, education, rate, and past performance.  
2. **internal\_partner\_search(domain\_or\_cert: str) \-\> str**:  
   * Queries Supabase consortium\_partners for matching corporate accreditations (ISO 27001, CMMI) or domains.  
   * Returns partner profile summaries, turnover tiers, and past contracts.  
3. **external\_talent\_discovery(role\_title: str, required\_cert: str \= "", location: str \= "") \-\> str**:  
   * Calls DuckDuckGoSearchTool using Boolean syntax: site:linkedin.com/in/ "{role\_title}" "{required\_cert}" {location}.  
   * Fallback: If no results, searches for prevailing compensation day rates and role benchmarks.  
4. **external\_partner\_discovery(required\_domain: str, required\_cert: str \= "") \-\> str**:  
   * Calls DuckDuckGoSearchTool using syntax: site:clutch.co "{required\_domain}" "{required\_cert}" enterprise IT partner.  
   * Fallback: General web search for certified consulting firms matching the target jurisdiction.

**Verification Gate 2:** Execute a standalone unit test querying internal\_cv\_search and external\_talent\_discovery; ensure structured string responses without unhandled network exceptions.

### **Phase 3: The 5 Discrete Agent Modules (agents/)**

Every agent must be configured with an explicit Role, Goal, Backstory, assigned tools, and LLM configuration using ChatGroq(model\_name="openai/gpt-oss-120b").

#### **1\. Agent 1: Senior Procurement & Compliance Specialist (agents/analyzer.py)**

* **Role:** Senior Procurement & Compliance Specialist  
* **Goal:** Deconstruct RFP text, identify the governing procurement framework (World Bank SPD, ADB QCBS, PPRA, or Commercial), extract mandatory forms (TECH-1 to TECH-6), gatekeeper rules, required personnel, and consortium mandates.  
* **Output Contract:** Generates structured JSON or Markdown sections:  
  * \[FRAMEWORK\]: Detected framework and mandatory submission form list.  
  * \[PASS\_FAIL\_GATES\]: Turnover minimums, registrations, certifications.  
  * \[PERSONNEL\_MANDATES\]: Role titles, minimum years of experience, degrees, required certifications.  
  * \[TEAMING\_MANDATES\]: Missing corporate capabilities requiring joint venture partners.

#### **2\. Agent 2: Market & Competitor Intelligence Analyst (agents/market\_intel.py)**

* **Role:** Competitive Intelligence & Industry Benchmarking Analyst  
* **Goal:** Use DuckDuckGo to extract prevailing day rates, technical reference architectures, and winning differentiators for the target jurisdiction.  
* **Tools:** DuckDuckGoSearchTool

#### **3\. Agent 3: Resource & Consortium Planner (agents/resource\_planner.py)**

* **Role:** Principal Resource Allocator & Strategic Teaming Director  
* **Goal:** Query team\_cvs and consortium\_partners, use external discovery for gaps, calculate FTE level of effort, and **transform raw resumes into the 8-part World Bank / ADB Form TECH-6 format**.  
* **Tools:** internal\_cv\_search, internal\_partner\_search, external\_talent\_discovery, external\_partner\_discovery.  
* **Form TECH-6 Enforcement:**  
  1. Position Title and Assigned Role Number (e.g., Key Expert 1 \[K-1\]).  
  2. Personal Information (Full name, nationality, residence).  
  3. Formal Education (Degrees, institutions, years).  
  4. Professional Accreditations & Licenses (PMP, CISSP, PEC, etc.).  
  5. Language Proficiency Matrix (Speaking/Reading/Writing ratings).  
  6. Chronological Employment Record (10–15 years history).  
  7. Adequacy for the Assignment (Assignment Mapping Matrix matching RFP tasks to past projects).  
  8. Statutory Certification & Attestation Block (legal truth declaration).

#### **4\. Agent 4: Lead Technical Proposal Architect (agents/writer.py)**

* **Role:** Principal Technical Bid Writer & Solution Architect  
* **Goal:** Draft the complete technical proposal structured strictly to confirmed standard forms:  
  * Section 1: Form TECH-1 (Submission Letter).  
  * Section 2: Form TECH-2 (Consultant Org, Experience & Consortium Partner Profiles).  
  * Section 3: Form TECH-3 (Comments on TOR & Counterpart Staff).  
  * Section 4: Form TECH-4 (Approach, Methodology & Work Plan).  
  * Section 5: Form TECH-5 (Work Schedule & Deliverables Table).  
  * Section 6: Form TECH-6 (Team Composition & Formatted Biodata CVs from Agent 3).

#### **5\. Agent 5: Executive Compliance & QA Auditor (agents/reviewer.py)**

* **Role:** Executive Bid Auditor & Quality Controller  
* **Goal:** Perform an adversarial red-team audit across the 4 core dimensions: Evidence, Accuracy, Completeness, and Quality. Verify Form TECH-6 compliance, compute an empirical score (![][image1]), rectify draft deficiencies, and produce the final submission-ready dossier.

**Verification Gate 3:** Validate prompt contracts and ensure each agent's expected output matches the handoff payload required by downstream tasks.

### **Phase 4: Stage-Gated Pipeline Orchestration (crew.py)**

Implement two discrete kickoff functions to maintain the **Pattern 1 Stage-Gated Execution**:

def run\_analyzer\_phase(rfp\_payload: dict, step\_callback=None) \-\> str:  
    """  
    Phase 1: Ingestion & Regulatory Deconstruction.  
    Executes Agent 1 only and returns parsed mandates for human review.  
    """  
    analyzer \= create\_analyzer\_agent()  
    task \= create\_analysis\_task(analyzer, rfp\_payload)  
    crew \= Crew(  
        agents=\[analyzer\],  
        tasks=\[task\],  
        process=Process.sequential,  
        step\_callback=step\_callback,  
        verbose=True  
    )  
    return str(crew.kickoff())

def run\_proposal\_generation\_phase(  
    analyzer\_output: str,  
    confirmed\_framework: str,  
    extra\_staffing\_notes: str \= "",  
    extra\_partner\_notes: str \= "",  
    step\_callback=None  
) \-\> dict:  
    """  
    Phase 2: Synthesis, Resourcing & Red-Team Audit.  
    Executes Agents 2, 3, 4, and 5 with real-time callbacks.  
    """  
    \# 1\. Instantiate Agents 2, 3, 4, 5  
    \# 2\. Build tasks with upstream dependencies  
    \# 3\. Assemble and kickoff sequential Crew  
    \# 4\. Return dict containing final\_proposal and compliance\_score

#### **Step Callback Bridge:**

Wire step\_callback to intercept tool actions and thoughts, routing them to the CollaborationMonitor in ui/collaboration\_board.py using keyword heuristics:

* "market" ![][image2] step2a\_market  
* "resource" / "consortium" ![][image2] step2b\_resource  
* "writer" ![][image2] step3\_writer  
* "reviewer" / "audit" ![][image2] step4\_reviewer

**Verification Gate 4:** Run a headless CLI test verifying Phase 1 output feeds cleanly into Phase 2 without variable mismatch or state corruption.

### **Phase 5: Mission Control UI & HITL Cockpit (app.py & ui/collaboration\_board.py)**

#### **Deliverable 5.1: Real-Time Execution Board (ui/collaboration\_board.py)**

Implement CollaborationMonitor with:

* Real-time timer and status badges (⏳ QUEUED, ⚡ RUNNING, ✅ DONE).  
* Two-column parallel topology for Stream A (Market Intel) and Stream B (Resource & JV Planner).  
* Inline Current Processing: micro-tickers.  
* Expandable per-agent ReAct deep-trace tabs (📋 Analyzer, 🌐 Market Intel, 👥 Resource & JV, ✍️️ Writer, ⚖️ Auditor).

#### **Deliverable 5.2: Streamlit Application (app.py)**

Build a 4-tab workspace layout with authenticated gating:

* **Auth Gateway:** Login / Sign-up with email and password via Supabase Auth.  
* **Tab 1: Bid Studio (/studio)**:  
  * **Stage 1 (Ingestion):** Inputs for Project Title, Client Name, and RFP Text (or .pdf/.txt upload).  
  * **Stage 2 (HITL Checkpoint Cockpit):**  
    * *Section A:* Detected donor framework selector (World Bank, ADB, PPRA, Commercial). User can confirm or override via dropdown.  
    * *Section B:* Extracted staffing roles and corporate accreditations display. Uploader to inject candidate CVs directly into team\_cvs.  
    * *Section C:* **"🚀 Confirm Guidelines & Proceed to Proposal Synthesis"** button.  
  * **Stage 3 (Live Execution):** Renders the CollaborationMonitor.  
  * **Stage 4 (Audited Bid Studio):** Displays Compliance Scorecard (![][image1]), full markdown proposal viewer, and one-click .md / .txt download buttons.  
* **Tab 2: Talent Bench Manager (/bench)**: Full CRUD table for internal employee records (team\_cvs).  
* **Tab 3: Consortium & Partner Directory (/partners)**: Full CRUD table for vetted teaming partners (consortium\_partners).  
* **Tab 4: Proposal Archive (/history)**: Repository of previously generated bid dossiers saved under auth.uid().

**Verification Gate 5:** Perform end-to-end user acceptance testing: User Sign-up ![][image2] Insert bench member ![][image2] Analyze RFP ![][image2] Confirm World Bank framework at Checkpoint ![][image2] Monitor live execution ![][image2] Download audited proposal.

## **4\. Multilateral Donor Standard Forms Reference Guide**

The development agent must ensure Agent 4 writes to the following explicit section headers when World Bank or ADB frameworks are confirmed:

\================================================================================  
SECTION 1: FORM TECH-1 — TECHNICAL PROPOSAL SUBMISSION FORM  
• Formal Letter of Submission to the Donor / Client Authority  
• Statement of Period of Validity (e.g., 90/120 days)  
• Joint Venture Declaration & Confirmation of Joint-and-Several Liability  
• Statutory Attestation against Sanctions & Debarment Lists

SECTION 2: FORM TECH-2 — CONSULTANT’S ORGANIZATION AND EXPERIENCE  
• Part A: Consultant Organization & Corporate Background  
• Part B: Consultant Experience (List of min. 3 completed projects of similar scale)  
• Part C: Consortium / Joint Venture Partner Credentials & Responsibility Division

SECTION 3: FORM TECH-3 — COMMENTS AND SUGGESTIONS ON THE TOR & COUNTERPART STAFF  
• Comments on the Terms of Reference to improve project outcomes  
• Counterpart staff and facility requirements from the Client

SECTION 4: FORM TECH-4 — DESCRIPTION OF APPROACH, METHODOLOGY, AND WORK PLAN  
• Technical Approach and Architectural Methodology  
• Work Plan, Milestones, and Work Breakdown Structure (WBS)  
• Organization, Governance, and Staffing Deployment Structure

SECTION 5: FORM TECH-5 — WORK SCHEDULE AND PLANNING FOR DELIVERABLES  
• Phase-by-phase implementation schedule (Weeks/Months)  
• Deliverables submission milestones and client review intervals  
• FTE allocation table per milestone

SECTION 6: FORM TECH-6 — TEAM COMPOSITION, ASSIGNMENT, AND FORMATTED BIODATA CVS  
• Comprehensive Staffing Table (Name, Assigned Position, Inputs in Person-Months)  
• Mandatory 8-Part Formatted Biodata CVs for all proposed Key Personnel  
\================================================================================

## **5\. Dev Agent Runbook & Defensive Failure Recovery**

1. **Handling DuckDuckGo Rate Limits:**  
   * If DuckDuckGo search queries return HTTP 429 or empty results, wrap the call in a try...except block that falls back to generalized domain queries without throwing unhandled exceptions.  
2. **Handling Empty Bench Queries:**  
   * If team\_cvs returns 0 candidates matching a mandatory certification (e.g., CISSP), the tool must return an explicit warning string: \[INTERNAL BENCH VACANCY: CISSP required. Sourcing external talent benchmark\]. This triggers Agent 3's external discovery tool.  
3. **Session State Protection in Streamlit:**  
   * Never store unpicklable CrewAI objects (e.g., active thread instances) in st.session\_state. Store only JSON-serializable dictionaries and raw text strings.  
4. **LLM Context Window Management:**  
   * Instruct Agent 1 to extract concise compliance matrices rather than regurgitating raw RFP boilerplate, preventing context window truncation in downstream agents.

## **6\. Execution Command Sequence for Dev Agent**

\# 1\. Environment Verification  
python \-V \# Must output Python 3.11.x or 3.12.x  
python \-m venv venv  
source venv/bin/activate \# or venv\\Scripts\\activate on Windows

\# 2\. Dependency Installation  
pip install \--upgrade pip  
pip install \-r requirements.txt

\# 3\. Database Migration  
\# Run database/schema.sql inside the Supabase Project SQL Editor

\# 4\. Configuration Setup  
\# Ensure .streamlit/secrets.toml contains GROQ\_API\_KEY, SUPABASE\_URL, SUPABASE\_KEY

\# 5\. Launch Application  
streamlit run app.py  


[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEUAAAAZCAYAAABnweOlAAADYElEQVR4Xu1X3YtNURSfGSR5IB6uOvfefb88+Iy5DyiUFCUPCC9ICeHF8KDwQPKg5IXwB0jiQSFTFE/mgfFClPIx+QyDmatuY2a6rt+6s/bMumv2ueecB6VxfrU6e/3Wx157nb33ubepKUaM/wqpVGpZJpOZqnmJbDY7X3NjFsaYSjqd3oWm3ITc0HYC+NXw+6n5hkgkEpMReBeBVUgnqGbtExXIcwkyS/MWsJ2BDEC+Y1FLtZ0A2wrIC67rssN+DvJG6ORHch07YxXybuM5qjIuEMlk0qMgPCeR7nnedE7SolwDgbgHkN+2OBQ1W/sQYCtBTgq9Dy/llPI5SLmsDvsevTie57TQb9sxH6dmcDtRx27LhwKCykhwVXGPIb8kFwWIbfVrCriVenF4IdM0xwuu22nEyebxHMesDttxPMZbnWCiHhsCJ96suCO6yCho1BTjs53ZfyuNsbh1Pj79kse4DDkv9A47Zj16Q3DulnMxdWcaRW0nnt6g5MMioClVyKCLx7xPeXxfLl74dEneDB2xAaEPHzeM99EFbPXQQBFtXGSr5JFsExe5SPJhQfkovkFTRr1B5vt43Eu6w+e55jHHQ3CvIJVcLjeFabpLStIvNBB4gibR33Bw67nILZIPCzPSlDkOG+X94cPXFizHyueJi9eAT1nqqOMOuFKonU+3Mk2CHbFA8Rt5UXQpdgQJ4q/JeMNNQRHzJM+2KqTXh69tfzw/ke7weebiJVDLAfjssDrGg+AW87gy4ukDe6dAlkg+PfR9p0V5kg8Lw03RO5BtNF+/D/+Sx353ymsXL9ACe49VUP9M6Y+fG0msbb/VnSgUChMp6G99ffQOZBstflRuruMij4/6+NR9fTQM30kWmP+w9ofeLnUnuMizimvXyaLAcFMgCx22C47cdDFWi8XiBEuQru8AznlLchZo6CGj7kA0Za+ey4gfeL4wjl3Bk2+QXBQgdg3lQKFrtY3AtuFLGMU/MuqLBP0zpEv4zKA42TiBcbB1a5L+vsi15fP5VODxsUDgFUiFn7Tt27RPGCD2K+QL5APkPT+Jeyv9cNcYmgdyD0W+w/OjtFuA/8b5ajsXvjntQzANfn3D1o1/0XN5HHzRjgXQ26c/f5qXQDM6IT36OMaIESNGjBgx/ln8AavBPi9Q9KC9AAAAAElFTkSuQmCC>

[image2]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAYCAYAAAAVibZIAAAAcklEQVR4XmNgGAWjYOCBvLz8XnQxigHQ0H/oYhQDOTk5GyAuQxenGABde05BQcEcXRwOZGVlTcjBQENvAQ3fh24eRQBo4F8gxYguTjYAGvgfXYwiAPT2BBUVFXZ0cYoA0JW/0cUoBkCXGqCLjYJRQEMAAMSsFY9fiDqtAAAAAElFTkSuQmCC>