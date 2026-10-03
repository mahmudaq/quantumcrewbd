# QuantumCrewBD — Product Requirements Document (PRD)

**Document Version:** 2.0.0

**Project Name:** QuantumCrewBD

**Competition / Event:** HEC PakAngels Aspire Hackathon 2 (Cohort 11)

**Strategic Lead & Visionary:** Dr. Irfan Ahmed Khan

**Project Lead:** Mahmud Qureshi

**Core Engineering Team:** Ali Uddin Khan, Durre Nayab, Saad Saeed

**Status:** Approved for Implementation

**Target Runtime:** Python 3.11 / 3.12 (CrewAI strict dependency compliance)

**Primary Stack:** CrewAI, Streamlit 1.38+, Supabase (Auth + PostgreSQL + RLS), Groq (`openai/gpt-oss-120b`), DuckDuckGo Search

## 1. Executive Summary & Strategic Product Vision

### 1.1 Vision Statement

To democratize high-value public procurement and enterprise bidding for small-to-midsize IT consultancies and digital agencies by deploying an autonomous, multi-agent proposal synthesis and compliance intelligence engine that eliminates gatekeeper disqualifications, formats standardized donor CVs, and reduces bid turnaround times from 40 billable hours to under 3 minutes.

### 1.2 Product Overview

**QuantumCrewBD** is an enterprise multi-tenant Business Process Automation (BPA) SaaS application. Built upon CrewAI's sequential and collaborative multi-agent architecture, the platform mirrors an elite capture, procurement, and technical writing team.

The system operates across a **Pattern 1 Stage-Gated Human-in-the-Loop (HITL) Checkpoint**, ensuring human governance over detected multilateral donor frameworks (World Bank, Asian Development Bank, PPRA, and enterprise standards) before initiating parallel market intelligence and resource/consortium planning. QuantumCrewBD automatically transforms raw candidate CVs into mandatory institutional biodata formats (e.g., World Bank Form `TECH-6`), matches corporate joint venture (JV) partners to bridge capability gaps, drafts submission-ready technical bids, and runs adversarial red-team compliance QA audits prior to submission.

### 1.3 Strategic Business Objectives & Hackathon Goals

1. **Compress Turnaround Latency:** Shrink technical proposal authoring and compliance matrix generation from **40 billable consultant hours to < 3 minutes**.

2. **0% Gatekeeper Disqualification:** Enforce binary pass/fail validation across financial turnover, statutory tax clearances, corporate accreditations (ISO/CMMI), and mandatory submission envelopes.

3. **Institutional Biodata Standardization:** Automatically translate unstructured resumes into 100% compliant 8-part donor CV formats (World Bank / ADB Form `TECH-6`) with Terms of Reference (TOR) task-adequacy mapping.

4. **Autonomous Consortium Formation:** Provide automated prime-subcontractor and joint venture matching against an organization’s compounding partner directory to satisfy high-barrier tender prerequisites.

5. **Multi-Tenant Data Privacy:** Guarantee complete cryptographic data isolation across organizational talent benches, consortium records, and bid archives using Supabase Row-Level Security (RLS).

## 2. Market Problem & Procurement Pain Points

Public tenders funded by multilateral development banks (MDBs) and national procurement authorities represent a multi-billion dollar market. However, mid-tier IT vendors and boutique consultancies suffer from structural procurement barriers:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 THE ENTERPRISE PROCUREMENT TRAP                                  │
├───────────────────────────────┬─────────────────────────────────┬────────────────────────────────┤
│ 1. Gatekeeper Rejection       │ 2. Standardized CV Mandates     │ 3. Consortium Deficits         │
│ • SPDs mandate strict forms   │ • World Bank/ADB reject regular │ • 60%+ tenders mandate JVs for │
│   (`TECH-1` to `TECH-6`).     │   corporate/LinkedIn CVs.       │   missing ISO/CMMI certs.      │
│ • 1 minor missing form yields │ • Manual 8-part reformatting    │ • Firms lack automated partner │
│   instant pre-scoring cutoff. │   takes 4+ hours per expert.    │   gap discovery.               │
├───────────────────────────────┼─────────────────────────────────┼────────────────────────────────┤
│ 4. Rate Benchmarking Guesswork│ 5. Hallucinated FTE Math        │ 6. Flawed Red-Team QA          │
│ • Unsubstantiated day rates   │ • Manual labor-loading results  │ • Capture teams rush bids      │
│   render commercial envelopes │   in WBS vs. milestone math     │   without adversarial audits   │
│   non-competitive.            │   discrepancies.                │   across Evidence & Accuracy.  │
└───────────────────────────────┴─────────────────────────────────┴────────────────────────────────┘

```

## 3. Target User Personas & User Journeys

### 3.1 Persona Profiles

#### Persona A: The Bid & Capture Director ("Bilal")

* **Role:** Lead Bid Specialist / Proposal Capture Manager at a 40-person IT consultancy.

* **Context:** Manages 5–8 concurrent public and enterprise tenders per month.

* **Core Frustration:** Spends 20+ hours reading 100-page World Bank SPDs, extracting submission forms manually, and hunting down CV formats across company network drives.

* **Journey in QuantumCrewBD:** Uploads the RFP document, confirms the detected World Bank SPD framework at the HITL Checkpoint, inspects auto-filled `TECH-1` to `TECH-6` sections, and exports a fully audited, submission-ready markdown dossier.

#### Persona B: The Head of People & Resourcing ("Sana")

* **Role:** Director of Talent & Resource Operations.

* **Context:** Responsible for staffing multi-month technical implementation projects.

* **Core Frustration:** Does not know which staff members meet mandatory RFP gatekeepers (e.g., "10+ years experience, CISSP, active secret clearance"). Manually editing employee resumes to match donor formats is agonizing and error-prone.

* **Journey in QuantumCrewBD:** Maintains the firm's centralized bench in the **Talent Bench Manager** (`team_cvs`). Observes the Resource Planner agent automatically match candidates, restructure their experience into standard Form `TECH-6` biodata blocks, and pull external web benchmarks for missing roles.

#### Persona C: The Managing Partner / Sign-Off Executive ("Tariq")

* **Role:** Managing Director / VP of Enterprise Alliances.

* **Context:** Legal and commercial sign-off authority for high-stakes proposals (\$500K–$5M).

* **Core Frustration:** Reluctant to sign off on generic, AI-generated proposals that hallucinate timelines, lack corporate liability clauses, or miss consortium prerequisites.

* **Journey in QuantumCrewBD:** Inspects the **Executive Compliance Scorecard (0–100%)** generated by the adversarial QA Auditor agent, reviews the verified consortium partner splits, and approves the bid with defensible audit trails.

## 4. Multi-Agent System Architecture (Pattern 1 HITL)

QuantumCrewBD executes through a decoupled, two-phase pipeline separated by a synchronous Streamlit Human-in-the-Loop approval gate. This architecture prevents headless browser thread-locking while guaranteeing user oversight of governing donor frameworks.

```
                               ┌───────────────────────────────────┐
                               │   Streamlit Web Client (Tenant)   │
                               └─────────────────┬─────────────────┘
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 PHASE 1: INGESTION & DECONSTRUCTION                              │
│                                                                                                  │
│   Agent 1: Senior Procurement & Compliance Specialist (`agents/analyzer.py`)                     │
│   • Ingests raw RFP text / documentation.                                                        │
│   • Classifies governing framework (World Bank SPD, ADB QCBS, PPRA SBD, Commercial).             │
│   • Extracts mandatory forms (`TECH-1` to `TECH-6`, `FIN-1` to `FIN-4`) & formatting rules.       │
│   • Isolates mandatory personnel credentials, turnover thresholds, and teaming prerequisites.   │
└────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                 │
                                                 ▼
════════════════════════════════════════════════════════════════════════════════════════════════════
 🛑 STAGE-GATED HITL CHECKPOINT (Streamlit Human-in-the-Loop Cockpit)
 
 [Section A: Donor Framework Governance]
  • Displays detected framework: e.g., "World Bank SPD (QCBS / Standard Forms TECH-1 to TECH-6)".
  • Human Action: Confirm detected standard OR override via dropdown (e.g., ADB FTP / PPRA SBD).
 
 [Section B: Staffing & Consortium Verification]
  • Displays mandatory roles and corporate prerequisites (e.g., ISO 27001, CMMI Level 3).
  • Compares against internal Supabase bench (`team_cvs` and `consortium_partners`).
  • Human Action: Upload missing candidate CVs (.pdf/.txt) or set preferred JV partners.
 
 [Section C: Explicit Authorization]
  • Human Action: Clicks [ 🚀 Confirm Guidelines & Proceed to Proposal Synthesis ].
════════════════════════════════════════════════════════════════════════════════════════════════════
                                                 │
                                                 ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                PHASE 2: SYNTHESIS, RESOURCING & QA                               │
│                                                                                                  │
│   ┌─────────────────────────────────────────┐   ┌────────────────────────────────────────────┐   │
│   │ Track A: Market Intel Analyst           │   │ Track B: Resource & Consortium Planner     │   │
│   │ (`agents/market_intel.py`)              │   │ (`agents/resource_planner.py`)             │   │
│   │ • Live DDG search for market day-rates  │   │ • Internal CV Bench Match (`team_cvs`)     │   │
│   │ • Prevailing tech stacks & DPI standards│   │ • Form TECH-6 Biodata Transformation       │   │
│   │ • Competitive win themes & diffs        │   │ • Consortium JV Partner Search (`partners`)│   │
│   └────────────────────┬────────────────────┘   └─────────────────────┬──────────────────────┘   │
│                        │                                              │                          │
│                        └──────────────────────┬───────────────────────┘                          │
│                                               │ Handoff: Benchmarks + TECH-6 CVs + JV Split      │
│                                               ▼                                                  │
│                        Agent 4: Lead Technical Proposal Architect                                │
│                        (`agents/writer.py`)                                                      │
│                        • Drafts strictly into confirmed Standard Forms (`TECH-1` to `TECH-6`)    │
│                        • Detailed System Architecture, WBS, Milestones & Consortium Rationale    │
│                                               │                                                  │
│                                               ▼ Handoff: Complete Draft Proposal Dossier         │
│                        Agent 5: Executive Compliance QA Auditor                                  │
│                        (`agents/reviewer.py`)                                                    │
│                        • Adversarial 4-Dimension Audit (Evidence, Accuracy, Completeness, Quality│
│                        • Validates Form TECH-6 CVs, page budgets & mandatory pass/fail rules     │
│                        • Generates Compliance Scorecard (0–100%) and polishes final bid text     │
└───────────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                                │
                                                ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                         SUPABASE PERSISTENCE & CLIENT DELIVERY                                   │
│   • Persists final audited dossier to `proposals` table under authenticated `user_id`.          │
│   • Streamlit displays Audited Bid Studio with one-click `.md` and `.txt` export capabilities.   │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

```

## 5. Multilateral Donor Frameworks & Standard Forms Support

QuantumCrewBD treats procurement compliance as an exact science. The platform includes explicit schema and prompt mapping for major international and domestic procurement regimes:

### 5.1 Supported Frameworks & Form Profiles

| 

| **Framework** | **Governing Documents** | **Mandatory Standard Submission Forms** | **Gatekeeper Rules & Penalties** | 
| **World Bank (WB)** | Standard Procurement Documents (SPD) for Consulting Services | `TECH-1`: Submission Letter  `TECH-2`: Org & Experience  `TECH-3`: Comments on TOR  `TECH-4`: Approach & Work Plan  `TECH-5`: Work Schedule & FTEs  `TECH-6`: Team & Standard Biodata CVs  `FIN-1` to `FIN-4`: Financials | Strict separation of technical and financial envelopes; mandatory joint-and-several liability clauses for Joint Ventures; immediate rejection for non-standard CV layouts. | 
| **Asian Development Bank (ADB)** | Single-Stage Two-Envelope (1S2E) / QCBS / FTP | Full Technical Proposal (FTP) narrative sections; standardized ADB biodata CV templates; national eligibility declarations. | Narrative page budgets (e.g., maximum 50 pages for FTP narrative); mandatory national eligibility affidavits; strict CV format adherence. | 
| **PPRA (Pakistan)** | Standard Bidding Documents (SBD) / Procurement of IT Systems | Technical Proposal Sheets, Active Taxpayer (ATL) verification, PEC/PSEB registration proofs, Joint Venture notarized deeds. | Binary disqualification if firm is not on active taxpayer list (FBR ATL) or lacks mandatory bid security formats. | 
| **Enterprise / Commercial** | Custom Statements of Work (SOW) & Corporate RFPs | Executive Summary, Technical Architecture, WBS, SLA Matrix, Commercial Pricing Schedule, Risk Register. | Tailored to client's proprietary evaluation rubric (e.g., 40% Architecture, 30% Personnel, 30% Pricing). | 

## 6. Standardized Donor CV Transformation Engine (Form TECH-6)

Submitting unstructured corporate or LinkedIn-style CVs is among the leading causes of disqualification in World Bank and ADB bids. Agent 3 systematically ingests candidate profiles and outputs the mandatory 8-part biodata standard:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│               MANDATORY WORLD BANK / ADB FORM TECH-6 BIODATA ARCHITECTURE                        │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Position Title and Assigned Role Number: (e.g., Key Expert 1 [K-1]: Project Director)         │
│ 2. Personal Information: Full legal name, date of birth, nationality, country of residence       │
│ 3. Formal Education: Degrees, educational institutions attended, graduation years               │
│ 4. Professional Accreditations & Licenses: PMP, CISSP, AWS Lead Architect, PEC license numbers    │
│ 5. Language Proficiency Matrix: Self-rating (Fair / Good / Excellent) for Speaking, Reading,    │
│    and Writing across all declared languages                                                     │
│ 6. Chronological Employment Record: Preceding 10–15 years of employment (Employer, Job Title,   │
│    exact start/end dates, location of performance)                                              │
│ 7. Adequacy for the Assignment (Assignment Mapping Matrix):                                      │
│    ┌──────────────────────────────────┬───────────────────────────────────────────────────────┐  │
│    │ Mandatory TOR Tasks Assigned:    │ Past Work that Best Illustrates Capability:           │  │
│    ├──────────────────────────────────┼───────────────────────────────────────────────────────┤  │
│    │ • Cloud Security Migration Lead  │ Project: National Health Registry Cloud Migration     │  │
│    │ • Zero-Trust IAM Architecture    │ Client: Ministry of Health, 2023-2024                 │  │
│    │ • ISO 27001 Controls Audit       │ Responsibilities: Led multi-region AWS deployment...  │  │
│    └──────────────────────────────────┴───────────────────────────────────────────────────────┘  │
│ 8. Statutory Certification & Attestation: Mandatory legal attestation clause confirming that all │
│    information is true, followed by date and signature authorization placeholders.               │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘

```

## 7. Functional Requirements & MoSCoW Prioritization

### 7.1 Priority P0: Must Have (Hackathon MVP Delivery)

#### FR-01: Multi-Tenant Supabase Authentication & RLS

* System shall support user Sign-Up, Sign-In, and Sign-Out via Supabase Auth.

* Database shall enforce Row-Level Security (`USING (auth.uid() = user_id)`) across `profiles`, `team_cvs`, `consortium_partners`, and `proposals`.

* Users shall never be able to access, modify, or inspect records belonging to other tenants.

#### FR-02: Pattern 1 Stage-Gated Human-in-the-Loop Checkpoint

* System shall halt Phase 1 execution cleanly in Streamlit after Agent 1 analyzes the tender.

* Checkpoint UI shall display the detected procurement framework, required standard forms (`TECH-1` to `TECH-6`), extracted key personnel roles, and consortium mandates.

* User shall have the ability to confirm or override the framework via a dropdown and inject additional candidate CVs or partner directives before authorizing Phase 2.

#### FR-03: Dual-Channel Talent & Consortium Bench Management

* System shall provide full CRUD management for internal employees in `team_cvs` (experience, certifications, clearance, rate, and bio).

* System shall provide CRUD management for vetted corporate partners in `consortium_partners` (domain, certifications, turnover, past performance).

* System shall equip Agent 3 with tools to query internal tables first before executing external web discovery searches via DuckDuckGo.

#### FR-04: Automated Donor CV Transformation Engine

* Agent 3 shall automatically restructure candidate biographies into the 8-part World Bank / ADB Form `TECH-6` format.

* System shall map extracted RFP TOR tasks to the candidate’s past performance records.

#### FR-05: Standard Forms Technical Proposal Authoring

* Agent 4 shall format proposals strictly according to confirmed standard forms:

  * World Bank / ADB: Forms `TECH-1`, `TECH-2`, `TECH-3`, `TECH-4`, `TECH-5`, and `TECH-6`.

  * Commercial: Executive Summary, System Architecture, WBS, Milestones, Commercials, and Risk Management.

#### FR-06: Adversarial Compliance QA Audit & Scorecard

* Agent 5 shall audit the draft proposal across the 4 core dimensions: Evidence, Accuracy, Completeness, and Quality.

* System shall compute an empirical compliance score: 

  $$
  \text{Compliance Score} = \left( \frac{\text{Passed Mandatory Criteria}}{\text{Total Mandatory Criteria}} \right) \times 100\%
  $$

* System shall display the audit findings report, highlight remaining risks, and persist the finalized bid in Supabase.

#### FR-07: Mission Control Execution Monitor

* UI shall render a two-tier real-time collaboration monitor displaying active node states, two-column parallel tracks (Market Intel vs. Resource Planner), handoff badges, and an expandable per-agent ReAct trace drawer.

### 7.2 Priority P1: Should Have (Post-Hackathon V1.1)

* **FR-08: Native File Ingestion:** Direct file parsing for multi-page `.pdf` and `.docx` RFP packets using PyMuPDF / docx2txt.

* **FR-09: Institutional PDF Dossier Export:** Generation of client-ready, styled PDF bid packages with automatic tables of contents, formal cover letters, and standard headers/footers.

* **FR-10: Standalone Consortium Scout Agent:** Decoupling Agent 3 into two discrete agents (`resource_planner.py` and `consortium_scout.py`) for specialized corporate teaming analysis.

### 7.3 Priority P2: Could Have (SaaS V2 Roadmap)

* **FR-11: Win-Probability ML Scoring:** Machine learning model trained on historical tender awards to predict win probabilities based on technical scoring weights and competitor profiles.

* **FR-12: Multi-User Collaboration & Role-Based Access:** Organization-level role management (e.g., Workspace Admin, Bid Editor, Read-Only Reviewer).

* **FR-13: CRM & Bid Portal Connectors:** Direct bidirectional integrations with Salesforce, HubSpot, and government procurement portals (e.g., SAM.gov, UN Development Business).

### 7.4 Priority Out of Scope (Explicitly Excluded)

* **NFR-Out-1:** Automated submission via government portal credential scraping (bids must be reviewed and submitted by authorized human signers).

* **NFR-Out-2:** Invoicing, accounting ledgers, or full post-award ERP financial management.

* **NFR-Out-3:** Native mobile applications (iOS/Android).

## 8. Non-Functional Requirements & Security Specifications

### 8.1 Data Privacy & Multi-Tenant Isolation

* **Cryptographic Tenancy:** All SQL queries originating from Streamlit must supply the active user's JWT. PostgreSQL Row-Level Security policies must strictly reject any cross-tenant data leakage.

* **API Credential Protection:** All model provider keys (Groq API, Supabase Anon Key) must be injected via Streamlit Secrets (`.streamlit/secrets.toml`) or environment variables, never committed to public version control.

### 8.2 Execution Performance & Latency Budgets

* **Phase 1 Execution (Analyzer):** Target completion within $\le 30$ seconds.

* **Phase 2 Execution (Synthesis, Resourcing & Audit):** Target completion within $\le 90$ seconds under Groq `openai/gpt-oss-120b` inference.

* **Database Query Latency:** All Supabase CRUD operations on `team_cvs` and `consortium_partners` must execute within $\le 250$ milliseconds.

### 8.3 Reliability & Deterministic Fallbacks

* **Search Fallbacks:** If DuckDuckGo search queries return zero results for obscure certifications, the tool must gracefully fall back to generalized queries without throwing unhandled exceptions.

* **Python Runtime Constraints:** The application runtime must remain strictly locked to Python **3.11** or **3.12** to prevent CrewAI dependency breaks associated with unpinned runtimes.

## 9. Streamlit Mission Control & UI Specification

The application delivers an enterprise workspace organized across four distinct functional tabs:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│  QuantumCrewBD Enterprise Mission Control (Streamlit Workspace)                                  │
├────────────────────┬────────────────────┬─────────────────────────────┬──────────────────────────┤
│ 🚀 Bid Studio      │ 👥 Talent Bench    │ 🏢 Consortium Directory     │ 📁 Proposal Archive      │
└────────────────────┴────────────────────┴─────────────────────────────┴──────────────────────────┘

```

### 9.1 Tab 1: Bid Studio (`/studio`)

* **Step 1 (Ingestion):** Input fields for Project Title, Client/Donor Name, Submission Deadline, and Raw RFP Text (with `.txt`/`.pdf` upload).

* **Step 2 (The HITL Checkpoint):** Interactive approval dashboard displaying detected framework (e.g., World Bank SPD), standard form list (`TECH-1` to `TECH-6`), extracted key roles, and consortium mandates. Provides one-click confirmation and CV injection widgets.

* **Step 3 (Live Mission Control):** Compact `CollaborationMonitor` featuring:

  * Status badges (`⏳ QUEUED`, `⚡ RUNNING`, `✅ DONE`).

  * Parallel execution topology (Stream A: Market Intel vs. Stream B: Resource & JV Planner).

  * Real-time `Processing: <action>` inline tickers.

  * Collapsible Per-Agent ReAct Deep Trace drawer (`[📋 Analyzer]`, `[🌐 Market Intel]`, `[👥 Resource & JV]`, `[✍️ Writer]`, `[⚖️ Auditor]`).

* **Step 4 (Audited Bid Review):** Metric card displaying the Compliance Score (0–100%), markdown dossier viewer, and one-click `.md` and `.txt` download buttons.

### 9.2 Tab 2: Talent Bench Manager (`/bench`)

* Interactive registration form to insert team profiles into `team_cvs`.

* Filterable table view of active personnel showing certifications, hourly rates, and past project references.

### 9.3 Tab 3: Consortium & Partner Directory (`/partners`)

* Partner registration form to insert corporate teaming partners into `consortium_partners`.

* Table view of vetted partners showing annual turnover tiers, CMMI/ISO certifications, and primary technical domains.

### 9.4 Tab 4: Proposal Archive (`/history`)

* Historical repository of past bid runs persisted under the user’s `auth.uid()`, allowing immediate review and download without consuming additional LLM tokens.

## 10. Multi-Agent Output Acceptance & Quality Gates

In strict accordance with the evaluation dimensions taught in the training program, all agent handoffs and the final bid dossier must satisfy the following verifiable criteria:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                        THE 4-DIMENSION AGENT QUALITY ACCEPTANCE GATES                            │
├────────────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ Dimension                      │ Verifiable Acceptance Gate Criterion                            │
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 1. Evidence                    │ • 100% of claimed candidate credentials and partner past        │
│                                │   performance citations must trace directly to verified         │
│                                │   records in `team_cvs`, `consortium_partners`, or live DDG     │
│                                │   search observations. Zero fabricated project references.      │
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 2. Accuracy                    │ • FTE allocations across project phases must balance:           │
│                                │   $$\sum (\text{Phase Days} \times \text{FTE}) = \text{Total}$$ │
│                                │ • All billing day-rates must align with Market Intel benchmarks.│
│                                │ • No hallucinated technology version numbers or obsolete stacks.│
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 3. Completeness                │ • 100% of mandatory submission forms dictated by the confirmed  │
│                                │   donor framework (`TECH-1` through `TECH-6`) must be present.  │
│                                │ • Zero omitted gatekeeper items from Agent 1's Compliance Matrix│
├────────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 4. Quality & Efficiency        │ • Proposal drafted in polished, professional technical English. │
│                                │ • All CVs must follow the 8-part Form TECH-6 biodata structure. │
│                                │ • Pipeline execution completed within latency thresholds.       │
└────────────────────────────────┴─────────────────────────────────────────────────────────────────┘

```

## 11. Hackathon Demonstration Script (3-Minute Live Pitch)

| **Timestamp** | **Screen / Visual Focus** | **Presenter Narration & Key Action** | 
| **0:00 – 0:30** | Slide 1: The Enterprise RFP Dilemma | *"Boutique IT consultancies forfeit high-value World Bank, ADB, and government tenders because of procurement bureaucracy, non-standard CV formats, and missing consortium accreditations. Introducing QuantumCrewBD."* | 
| **0:30 – 1:00** | Tab 1: Tender Ingestion & HITL Cockpit | *"We upload an 80-page World Bank Smart City tender. In 15 seconds, Agent 1 detects the World Bank SPD framework, identifies mandatory Forms TECH-1 through TECH-6, and flags an ISO 27001 requirement. At our Pattern 1 HITL Checkpoint, we confirm the standard with one click."* | 
| **1:00 – 1:45** | Tab 1: Mission Control Parallel Mesh | *"Watch our parallel tracks execute: Market Intel benchmarks local day-rates while our Resource Planner matches our internal Supabase bench, structures our Lead Architect into World Bank Form TECH-6, and queries our consortium directory to cover the ISO certification gap."* | 
| **1:45 – 2:30** | Tab 1: Synthesis & Adversarial Audit | *"Agent 4 drafts the complete bid strictly into Forms TECH-1 through TECH-6. Agent 5 red-teams the draft across Evidence, Accuracy, and Completeness, awarding a 96% compliance score and verifying zero gatekeeper omissions."* | 
| **2:30 – 3:00** | Tab 2 & 4: Multi-Tenant Architecture | *"All company CVs, consortium partners, and bid dossiers are protected under Supabase Row-Level Security. QuantumCrewBD turns a 40-hour drafting nightmare into a 3-minute winning bid."* | 

## 12. Implementation Roadmap & Release Milestones

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             HACKATHON EXECUTION TIMELINE (DAY 1)                                 │
├───────────────────────────────────┬──────────────┬───────────────────────────────────────────────┤
│ Milestone                         │ Duration     │ Deliverables & Acceptance Verification        │
├───────────────────────────────────┼──────────────┼───────────────────────────────────────────────┤
│ M1: Cloud Persistence & Auth      │ 30 Mins      │ • Run `database/schema.sql` on Supabase.       │
│                                   │              │ • Verify RLS isolation between 2 user accounts│
│                                   │              │ • Implement `database/supabase_client.py`.    │
├───────────────────────────────────┼──────────────┼───────────────────────────────────────────────┤
│ M2: Tooling & Sourcing Engine     │ 45 Mins      │ • Implement `tools.py` (internal CV/partner   │
│                                   │              │   queries + DuckDuckGo web search wrappers).  │
│                                   │              │ • Unit test Form TECH-6 parser logic.         │
├───────────────────────────────────┼──────────────┼───────────────────────────────────────────────┤
│ M3: 5-Agent Crew Pipeline         │ 45 Mins      │ • Implement modules in `agents/`.             │
│                                   │              │ • Build two-phase pipeline in `crew.py`.      │
│                                   │              │ • Wire `step_callback` for live tickers.      │
├───────────────────────────────────┼──────────────┼───────────────────────────────────────────────┤
│ M4: Streamlit UI & HITL Cockpit   │ 60 Mins      │ • Build `app.py` with 4-tab workspace.        │
│                                   │              │ • Embed `CollaborationMonitor` execution view.│
│                                   │              │ • Wire Pattern 1 stage-gated review flow.     │
├───────────────────────────────────┼──────────────┼───────────────────────────────────────────────┤
│ M5: End-to-End Tender Validation  │ 45 Mins      │ • Ingest sample World Bank SPD tender.        │
│                                   │              │ • Validate 0–100% compliance audit scorecard. │
│                                   │              │ • Rehearse live 3-minute hackathon pitch.     │
└───────────────────────────────────┴──────────────┴───────────────────────────────────────────────┘

```