"""The five agent modules.

  analyzer          Agent 1 — RFP & Compliance Deconstruction (triggers HITL)
  market_intel      Agent 2 — Market & Competitor Intelligence   (Track B)
  resource_planner  Agent 3 — Resource & Consortium + TECH-6      (Track A)
  writer            Agent 4 — Lead Technical Proposal Architect
  reviewer          Agent 5 — Executive Compliance & QA Auditor

Importing a submodule pulls in CrewAI. The prompt/parse helpers are importable
without it for tests that only exercise the contract layer.
"""

from __future__ import annotations

__all__ = ["analyzer", "market_intel", "resource_planner", "writer", "reviewer"]
