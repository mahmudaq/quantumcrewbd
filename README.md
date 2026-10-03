# QuantumCrewBD

Enterprise multi-tenant **procurement intelligence & proposal synthesis** platform —
multi-agent (CrewAI) automation of public-procurement bid response.

**Project:** HEC PakAngels Aspire Hackathon 2, Cohort 11
**Strategic Lead:** Dr. Irfan Ahmed Khan · **Project Lead:** Mahmud Qureshi
**Engineering:** Ali Uddin Khan, Durre Nayab, Saad Saeed

---

## Repository layout

| Path | Contents |
|---|---|
| `docs/01-Received/` | Supplied source documents (MVP spec, PRD, implementation plans) |
| `docs/02-Sent/` | Deliverables produced by the engineering team |
| `docs/03-Working/` | Working artifacts (dependency probes, scratch) |
| `docs/04-Reference/` | Reference material, recovered formulas, extracted figures |
| `app/` | Application source — *to be added in Phase 1* |

## Status

- Infrastructure access verified: Supabase project live, CrewAI PAT valid, Groq LLM key valid.
- End-to-end development plan delivered → see `docs/02-Sent/`.
- **Not yet started:** application code (awaiting sample tender corpus).

## Getting started

```bash
# credentials are NOT in this repo — they live in the team's secret store
cp .env.example .env   # then fill from the vault
uv venv --python 3.12 && uv pip install -r app/requirements.txt
```

## Key references

- **Development plan:** `docs/02-Sent/QuantumCrewBD_E2E_Development_Plan_v1.0.0.md`
- **Formulas & targets:** `docs/04-Reference/formulas.md`
- **Project notes / verified state:** `docs/project-notes.md`
- **Document provenance:** `docs/01-Received/PROVENANCE.md`
