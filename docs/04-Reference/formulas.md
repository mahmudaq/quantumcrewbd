# Recovered Formulas & Quantitative Targets

Extracted from the embedded formula images in the received documents
(base64 was mangled in the converted renditions; recovered by decoding the PNGs
and reading them directly). Source of truth = the two clean v2.0.0 originals.

## 1. Compliance Score (Agent 5, FR-06)

$$\text{Compliance Score} = \left( \frac{\text{Passed Mandatory Criteria}}{\text{Total Mandatory Criteria}} \right) \times 100\%$$

- Range 0–100%, integer, displayed as a metric card.
- Numerator/denominator = mandatory criteria from Agent 1's Compliance Matrix.
- Stored in `proposals.compliance_score INT`.

## 2. Level of Effort / Total Mandays (Agent 3)

$$\text{Total Mandays} = \sum \left( \text{Phase Duration (Days)} \times \text{FTE Allocation} \right)$$

- Enforced as an Accuracy gate (PRD §10): the FTE table must balance.
- Agent 5 re-computes and flags discrepancies as Accuracy defects.

## 3. ReAct Trace Model (PRD §6.2)

$$\text{Thought} \longrightarrow \text{Action (Tool Call + Arguments)} \longrightarrow \text{Observation}$$

## 4. Latency Budgets (PRD §8.2 — clean original)

| Target | Bound |
|---|---|
| Phase 1 (Analyzer) completion | **≤ 30 s** |
| Phase 2 (Synthesis + Resourcing + Audit) completion | **≤ 90 s** |
| Supabase CRUD on `team_cvs` / `consortium_partners` | **≤ 250 ms** |

> Note: the *lossy* Engineering Implementation doc appeared to state ≤180 s for
> Phase 2. The clean PRD original says **≤ 90 s**. The PRD governs.

## 5. Strategic KPI

40 billable consultant hours → **< 3 minutes** end-to-end.
