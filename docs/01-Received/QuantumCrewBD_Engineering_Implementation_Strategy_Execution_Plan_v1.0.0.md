# **QuantumCrewBD — Engineering Implementation Strategy & Execution Plan**

**Document Version:** 1.0.0

**Target Environment:** Python 3.11 / 3.12, CrewAI, Streamlit, Supabase

**Project:** QuantumCrewBD (HEC PakAngels Aspire Hackathon 2\)

## **1\. Architectural Answer: Should You Hand the MVP to CrewAI's Engine?**

### **1.1 What CrewAI's Built-in Tooling (crewai create crew) Actually Does**

CrewAI includes a CLI command (crewai create crew \<project\_name\>) that scaffolds a project. However, it is essential to understand its structural boundaries:

* **What it generates:** A minimal boilerplate containing YAML configuration files (agents.yaml, tasks.yaml) and a basic Python wrapper for a CLI-only agent run.  
* **What it CANNOT build:**  
  1. **Multi-Tenant Persistence:** It has no concept of PostgreSQL schemas, Supabase Auth tokens, or Row-Level Security (RLS) policies.  
  2. **Human-in-the-Loop Web UI:** It does not generate Streamlit interfaces, session state controllers, or the Pattern 1 Stage-Gated approval checkpoint.  
  3. **Custom Procurement Tools:** It will not implement database querying tools for team\_cvs and consortium\_partners or specialized DuckDuckGo searches.  
  4. **Domain Formats:** It will not implement the 8-part World Bank Form TECH-6 biodata transformation or institutional donor form logic (TECH-1 to TECH-6).

### **1.2 The Risk of Monolithic Generation**

Attempting to feed an entire 15-page MVP specification into a single code generation prompt will lead to:

* **Context window truncation** and truncated Python files.  
* **Hallucinated or deprecated imports** (e.g., mixing legacy LangChain tools with current CrewAI syntax).  
* **Broken callback bridges** between CrewAI execution threads and Streamlit re-renders.

## **2\. The Recommended Plan: Modular "Bottom-Up" Construction**

As demonstrated in Week 5 (Practice Session 2\) and Week 6 (Main Session 1\) of the Aspire Training Program, the proven development approach for agentic hackathon MVPs is **Modular Bottom-Up Construction**.

We build the system layer by layer so that each component can be verified independently before the next is layered on top:

┌─────────────────────────────────────────────────────────────────────────────────┐  
│                          MODULAR CONSTRUCTION PHASES                            │  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 1: Foundation & Persistence                                               │  
│ • \`requirements.txt\` (pinned dependencies)                                      │  
│ • \`database/schema.sql\` (Supabase DDL \+ RLS for profiles, CVs, partners, bids)   │  
│ • \`database/supabase\_client.py\` (Auth & client factory)                         │  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 2: Sourcing & Search Tool Suite                                           │  
│ • \`tools.py\` (Internal CV queries, Partner bench lookups, DuckDuckGo searches)  │  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 3: The 5 Discrete Agent Modules                                           │  
│ • \`agents/analyzer.py\` (Framework detection & SOW parsing)                      │  
│ • \`agents/market\_intel.py\` (Pricing benchmarks & win themes)                    │  
│ • \`agents/resource\_planner.py\` (Bench matching & Form TECH-6 transformation)    │  
│ • \`agents/writer.py\` (Donor standard forms drafting: TECH-1 to TECH-6)          │  
│ • \`agents/reviewer.py\` (4-Dimension QA audit: Evidence, Accuracy, etc.)         │  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 4: Stage-Gated Pipeline Orchestrator                                      │  
│ • \`crew.py\` (Phase 1 Analyzer kickoff \+ Phase 2 Synthesis kickoff with callbacks)│  
├─────────────────────────────────────────────────────────────────────────────────┤  
│ Phase 5: Mission Control UI & Checkpoint Cockpit                                │  
│ • \`ui/collaboration\_board.py\` (Real-time parallel execution monitor & tickers)  │  
│ • \`app.py\` (Supabase Auth gateway, Talent Bench tab, Consortium tab, Studio)    │  
└─────────────────────────────────────────────────────────────────────────────────┘

## **3\. Detailed Phase Breakdown & Verification Gates**

### **Phase 1: Environment, Dependencies & Cloud Persistence**

* **Artifacts:**  
  * requirements.txt: Strict dependency locking (crewai, crewai-tools, streamlit, supabase, langchain-groq, duckduckgo-search).  
  * database/schema.sql: Complete DDL creating profiles, team\_cvs, consortium\_partners, and proposals with RLS policies enabled.  
  * database/supabase\_client.py: Thread-safe Supabase client initialization supporting both Streamlit secrets and environment variables.  
* **Verification Gate:** Run schema.sql inside the Supabase SQL editor; verify that test queries enforce RLS under auth.uid().

### **Phase 2: The Custom Sourcing Tool Suite**

* **Artifacts:**  
  * tools.py: Wraps internal Supabase lookup functions (internal\_cv\_search, internal\_partner\_search) using CrewAI's @tool decorator, paired with defensive DuckDuckGo web search wrappers (external\_talent\_discovery, external\_partner\_discovery).  
* **Verification Gate:** Run a standalone test script verifying that calling internal\_cv\_search("Cloud Architect") correctly queries Supabase and returns structured candidate text.

### **Phase 3: Agent & Task Implementations**

* **Artifacts:**  
  * Dedicated files in agents/:  
    * analyzer.py: Senior Procurement Specialist (detects World Bank, ADB, PPRA).  
    * market\_intel.py: Market Intelligence Analyst.  
    * resource\_planner.py: Resource & Consortium Planner (enforces 8-part Form TECH-6 biodata).  
    * writer.py: Proposal Architect (drafts TECH-1 through TECH-6).  
    * reviewer.py: Compliance QA Auditor (computes 0–100% compliance score).  
* **Verification Gate:** Verify agent prompt contracts and expected outputs match the specifications in docs/AGENT\_RESPONSIBILITIES\_SPEC.md.

### **Phase 4: Two-Phase Pipeline Orchestration (crew.py)**

* **Artifacts:**  
  * crew.py: Implements the Pattern 1 Stage-Gated split:  
    * run\_analyzer\_phase(rfp\_payload): Runs Agent 1 and returns the extracted framework and mandates for user review.  
    * run\_proposal\_generation\_phase(confirmed\_framework, mandates, extra\_cvs, monitor): Runs Agents 2, 3, 4, and 5 with real-time step\_callback hooks.  
* **Verification Gate:** Execute a mock headless two-phase run to confirm clean data handoff between Phase 1 and Phase 2\.

### **Phase 5: Streamlit Mission Control Frontend**

* **Artifacts:**  
  * ui/collaboration\_board.py: Compact execution view with parallel tracks (Market Intel vs. Resource Planner) and granular ReAct trace tabs.  
  * app.py: Full multi-page tabbed interface:  
    * Auth Gateway (Sign-up, Sign-in with session retention).  
    * Tab 1: Bid Studio with the Stage-Gated HITL Checkpoint.  
    * Tab 2: Talent Bench Manager (team\_cvs CRUD).  
    * Tab 3: Consortium & Partner Directory (consortium\_partners CRUD).  
    * Tab 4: Proposal Archive (instant markdown/txt download).  
* **Verification Gate:** End-to-end user journey: Register account ![][image1] Add bench member ![][image1] Upload sample RFP ![][image1] Confirm donor guidelines at Checkpoint ![][image1] Watch live execution ![][image1] Download audited bid dossier.

## **4\. Next Step Recommendation**

We will execute **Phase 1** immediately:

1. requirements.txt  
2. database/schema.sql  
3. database/supabase\_client.py

This gives your team the exact database and dependency foundation needed before wiring the agents and frontend.

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABUAAAAYCAYAAAAVibZIAAAAcklEQVR4XmNgGAWjYOCBvLz8XnQxigHQ0H/oYhQDOTk5GyAuQxenGABde05BQcEcXRwOZGVlTcjBQENvAQ3fh24eRQBo4F8gxYguTjYAGvgfXYwiAPT2BBUVFXZ0cYoA0JW/0cUoBkCXGqCLjYJRQEMAAMSsFY9fiDqtAAAAAElFTkSuQmCC>