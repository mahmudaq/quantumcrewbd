"""QuantumCrewBD — multi-tenant autonomous bid-production platform.

Run locally:  streamlit run app.py

Architecture notes that matter for correctness:

* **`st.session_state` holds only JSON-serialisable data.** CrewAI agent, task
  and crew objects are never stored — they are built fresh inside a run. Storing
  them breaks on Streamlit's next rerun, because the objects are not picklable
  and Streamlit will try to hash them.
* **One run at a time per session.** The run button is disabled while a run is
  in flight (`st.session_state.running`), and results land in session state
  under plain dicts, so a browser refresh mid-run degrades to "no results yet"
  rather than a half-written object graph.
* **The HITL checkpoint is a hard stop.** Phase 2 cannot start until the user
  presses Authorize on the framework the analyzer proposed. That is deliberate:
  a wrong framework silently produces a complete, well-formatted proposal in the
  wrong template, which is worse than producing nothing.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import streamlit as st

from database.supabase_client import get_supabase_client, get_user_client
from orchestration.monitor import AGENT_LABEL, EventBridge
from orchestration.pipeline import (
    PhaseTimings,
    run_analyzer_phase,
    run_proposal_generation_phase,
)

st.set_page_config(page_title="QuantumCrewBD", page_icon="🏗️", layout="wide")

FRAMEWORK_OPTIONS = [
    "World Bank SPD",
    "ADB Standard Bidding Document",
    "PPRA SBD (Pakistan)",
    "Single-Stage Two-Envelope",
    "Unknown",
]


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #

def _init_state() -> None:
    defaults = {
        "authed": False,
        "access_token": None,
        "user_id": None,
        "user_email": None,
        "phase1": None,          # dict, not a Pydantic/CrewAI object
        "phase1_raw": "",
        "phase2": None,          # dict
        "events": [],            # list[dict] — JSON-serialisable
        "running": False,
        "timings": {},
        "injected_cvs": [],
        "confirmed_framework": None,
        "proposal_id": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


_init_state()


def _client():
    """A user-scoped Supabase client, or None when signed out.

    R-04: the anon client sees zero rows under RLS. Every query must run as the
    signed-in user, so the access token has to travel with the client.
    """
    if not st.session_state.access_token:
        return None
    return get_user_client(st.session_state.access_token)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Sidebar — auth + bench
# --------------------------------------------------------------------------- #

def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 🏗️ QuantumCrewBD")
        st.caption("Autonomous Bid Production")

        if not st.session_state.authed:
            st.markdown("#### Sign in")
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            if st.button("Sign in", use_container_width=True):
                _do_login(email, password)
            st.caption("New here? Users are provisioned by an administrator.")
            return

        st.success(st.session_state.user_email or "signed in")
        if st.button("Sign out", use_container_width=True):
            for k in ("authed", "access_token", "user_id", "user_email",
                      "phase1", "phase1_raw", "phase2", "events",
                      "proposal_id", "confirmed_framework"):
                st.session_state[k] = None if k not in ("events",) else []
            st.session_state.authed = False
            st.rerun()

        st.divider()
        st.markdown("#### LLM configuration")
        _render_llm_settings()

        st.divider()
        st.markdown("#### Internal Bench")
        _render_bench()


def _do_login(email: str, password: str) -> None:
    """Sign in against Supabase Auth and keep the real JWT.

    The token is stored in session state (never on disk, never logged) because
    every RLS-scoped query needs it.
    """
    if not email or not password:
        st.warning("Enter an email and password.")
        return
    try:
        res = get_supabase_client().auth.sign_in_with_password(
            {"email": email, "password": password})
    except Exception as e:                                       # noqa: BLE001
        st.error(f"Sign-in failed: {e}")
        return
    if not getattr(res, "session", None):
        st.error("Sign-in returned no session — is the email confirmed?")
        return
    st.session_state.authed = True
    st.session_state.access_token = res.session.access_token
    st.session_state.user_id = res.user.id
    st.session_state.user_email = res.user.email
    st.rerun()


def _render_llm_settings() -> None:
    """Per-account provider/model override (the flexible-LLM requirement).

    Values here become the `overrides` passed into the pipeline, which the
    registry consults before its own defaults. An empty selection means "use the
    registry default", so leaving this alone changes nothing.
    """
    from llm.registry import PROVIDERS

    st.caption("Applied to this run only. Leave as-is for the defaults.")
    provider = st.selectbox("Provider", ["(default)"] + sorted(PROVIDERS),
                            key="llm_provider")
    model = st.text_input("Model id (optional)", key="llm_model",
                          placeholder="e.g. deepseek/deepseek-v4.1-flash-fast")
    if st.button("Save to my account", key="llm_save"):
        client = _client()
        if client:
            try:
                client.table("profiles").update(
                    {"llm_provider": None if provider == "(default)" else provider,
                     "llm_model": model or None}
                ).eq("id", st.session_state.user_id).execute()
                st.success("Saved.")
            except Exception as e:                               # noqa: BLE001
                st.error(f"Could not save: {e}")


def _render_bench() -> None:
    """Add/view internal bench CVs. This is what Agent 3 searches."""
    client = _client()
    if not client:
        return
    with st.expander("Add a bench member", expanded=False):
        name = st.text_input("Full name", key="cv_name")
        role = st.text_input("Role / title", key="cv_role")
        years = st.number_input("Years experience", 0, 60, 5, key="cv_years")
        certs = st.text_input("Certifications (comma-separated)", key="cv_certs")
        skills = st.text_input("Skills (comma-separated)", key="cv_skills")
        summary = st.text_area("CV summary", key="cv_summary", height=80)
        if st.button("Add to bench", key="cv_add"):
            if not name or not summary:
                st.warning("Name and summary are required.")
            else:
                try:
                    client.table("team_cvs").insert({
                        "user_id": st.session_state.user_id,
                        "full_name": name,
                        "current_role": role,
                        "years_experience": int(years),
                        "certifications": [c.strip() for c in certs.split(",") if c.strip()],
                        "skills": [s.strip() for s in skills.split(",") if s.strip()],
                        "cv_summary": summary,
                    }).execute()
                    st.success(f"Added {name}.")
                except Exception as e:                           # noqa: BLE001
                    st.error(f"Could not add: {e}")

    if st.button("Show bench", key="cv_show"):
        try:
            rows = client.table("team_cvs").select(
                "full_name,current_role,years_experience").execute().data or []
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.caption(f"{len(rows)} member(s) visible to this account.")
        except Exception as e:                                   # noqa: BLE001
            st.error(f"Could not read bench: {e}")


# --------------------------------------------------------------------------- #
# Tab 1 — Ingest
# --------------------------------------------------------------------------- #

def render_ingest() -> None:
    st.markdown("## 1 · Ingest RFP")

    left, right = st.columns([2, 1])
    with left:
        title = st.text_input("Project title", key="ing_title",
                              placeholder="Third-Party Feasibility Study …")
        client_name = st.text_input("Client / procuring entity", key="ing_client",
                                    placeholder="PHE Division, District X")
    with right:
        st.caption("The tender text stays in this session. Nothing is uploaded "
                   "until you generate a proposal.")

    uploaded = st.file_uploader("Tender document", type=["txt", "md", "pdf"],
                                key="ing_file")
    pasted = st.text_area("…or paste the tender text", key="ing_paste", height=180)

    raw = ""
    if pasted.strip():
        raw = pasted
    elif uploaded is not None:
        if uploaded.name.lower().endswith(".pdf"):
            try:
                import fitz  # pymupdf
                with fitz.open(stream=uploaded.read(), filetype="pdf") as doc:
                    raw = "\n".join(p.get_text() for p in doc)
            except Exception as e:                               # noqa: BLE001
                st.error(f"Could not read the PDF: {e}")
        else:
            raw = uploaded.read().decode("utf-8", errors="ignore")

    if raw:
        st.caption(f"{len(raw):,} characters loaded.")

    disabled = st.session_state.running or not raw.strip()
    if st.button("▶ Analyze tender", type="primary", disabled=disabled,
                 key="ing_run"):
        _run_phase1(raw, title, client_name)

    if st.session_state.phase1:
        _render_analysis(st.session_state.phase1)


def _run_phase1(raw: str, title: str, client_name: str) -> None:
    st.session_state.running = True
    st.session_state.events = []
    bridge = EventBridge()
    bridge.attach()
    overrides, settings = _llm_overrides()

    with st.status("Analyzing tender…", expanded=True) as status:
        st.write("Locating the Data Sheet and evaluation criteria…")
        t0 = time.time()
        try:
            res = run_analyzer_phase(raw, project_title=title,
                                     client_name=client_name, bridge=bridge,
                                     overrides=overrides, settings=settings)
        except Exception as e:                                   # noqa: BLE001
            bridge.detach()
            st.session_state.running = False
            status.update(label="Analysis failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            return
        bridge.detach()
        for ev in bridge.events():
            st.write(ev.message)

        st.session_state.phase1 = res.dossier.model_dump()
        st.session_state.phase1_raw = raw
        st.session_state.timings["phase1_s"] = res.elapsed_s
        st.session_state.confirmed_framework = None
        st.session_state.phase2 = None
        status.update(label=f"Analysis complete in {res.elapsed_s:.1f}s",
                      state="complete")
    st.session_state.running = False
    st.rerun()


def _render_analysis(d: dict) -> None:
    """Show the analysis and — critically — the HITL checkpoint."""
    st.divider()
    st.markdown("### Analysis")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Framework", d.get("detected_framework") or "—",
              help=f"confidence: {d.get('framework_confidence') or 'n/a'}")
    c2.metric("Selection method", d.get("selection_method") or "—")
    c3.metric("Envelope", d.get("envelope_scheme") or "—")
    pm = d.get("technical_pass_mark")
    c4.metric("Technical pass mark", pm if pm is not None else "not specified")

    if d.get("framework_signals"):
        st.caption("Detected from: " + "; ".join(d["framework_signals"]))

    with st.expander(f"Compliance matrix ({len(d.get('compliance_matrix') or [])} items)",
                     expanded=True):
        rows = d.get("compliance_matrix") or []
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No compliance items were extracted. Check the tender text.")

    col_a, col_b = st.columns(2)
    with col_a:
        with st.expander(f"Personnel mandates ({len(d.get('personnel_mandates') or [])})"):
            st.dataframe(d.get("personnel_mandates") or [],
                         use_container_width=True, hide_index=True)
        with st.expander(f"Teaming mandates ({len(d.get('teaming_mandates') or [])})"):
            st.dataframe(d.get("teaming_mandates") or [],
                         use_container_width=True, hide_index=True)
    with col_b:
        with st.expander("Required forms", expanded=True):
            forms = d.get("mandatory_forms") or []
            st.write(", ".join(forms) if forms else "None detected.")
        with st.expander("Scope of work"):
            st.write(d.get("scope_of_work") or "—")

    _render_checkpoint(d)


def _render_checkpoint(d: dict) -> None:
    """Pattern 1 — the Stage-Gated HITL Checkpoint.

    Section A: confirm or correct the framework (this picks the form template).
    Section B: inject a CV the bench does not hold.
    Section C: authorize Phase 2.
    """
    st.divider()
    st.markdown("### ⏸ Human checkpoint")
    st.caption("Phase 2 builds the full proposal. Confirm the framework first — "
               "it decides which form template every downstream agent uses.")

    with st.container(border=True):
        st.markdown("**A · Governing framework**")
        proposed = d.get("detected_framework") or "Unknown"
        idx = FRAMEWORK_OPTIONS.index(proposed) if proposed in FRAMEWORK_OPTIONS else 0
        chosen = st.selectbox("Confirm or correct", FRAMEWORK_OPTIONS, index=idx,
                              key="cp_framework")
        if chosen != proposed:
            st.warning(f"Overriding the detected framework ({proposed}). "
                       "The proposal will use the forms for this framework instead.")
        pass_mark = st.number_input(
            "Technical pass mark", min_value=0, max_value=100,
            value=int(d.get("technical_pass_mark") or 0), key="cp_pass_mark",
            help="Blank/0 means the tender does not state one.")
        if pass_mark and pass_mark != (d.get("technical_pass_mark") or 0):
            st.info(f"Overridden to {pass_mark}.")
        st.session_state.cp_pass_mark_final = pass_mark or None

    with st.container(border=True):
        st.markdown("**B · Personnel**")
        st.caption("Add a CV the internal bench does not hold. It is treated as "
                   "an injected bench record for this run only.")
        with st.expander("Inject a CV"):
            n = st.text_input("Full name", key="ic_name")
            r = st.text_input("Role", key="ic_role")
            y = st.number_input("Years", 0, 60, 10, key="ic_years")
            s = st.text_area("Relevant experience", key="ic_summary", height=70)
            if st.button("Add", key="ic_add"):
                if n and s:
                    st.session_state.injected_cvs.append(
                        {"full_name": n, "current_role": r,
                         "years_experience": int(y), "cv_summary": s})
                    st.success(f"Queued {n}.")
                else:
                    st.warning("Name and experience are required.")
        if st.session_state.injected_cvs:
            st.write(f"{len(st.session_state.injected_cvs)} CV(s) queued:")
            st.dataframe(st.session_state.injected_cvs, use_container_width=True,
                         hide_index=True)

    with st.container(border=True):
        st.markdown("**C · Authorize**")
        can = not st.session_state.running
        if st.button("✅ Authorize proposal generation", type="primary",
                     disabled=not can, key="cp_authorize"):
            _run_phase2(chosen)


# --------------------------------------------------------------------------- #
# Tab 2 — Execution
# --------------------------------------------------------------------------- #

def _run_phase2(framework: str) -> None:
    p1 = dict(st.session_state.phase1 or {})
    p1["detected_framework"] = framework
    if st.session_state.get("cp_pass_mark_final") is not None:
        p1["technical_pass_mark"] = st.session_state.cp_pass_mark_final

    from models.dossiers import RFPComplianceDossier
    try:
        analysis = RFPComplianceDossier.model_validate(p1)
    except Exception as e:                                       # noqa: BLE001
        st.error(f"The confirmed analysis is not valid: {e}")
        return

    st.session_state.running = True
    st.session_state.events = []
    st.session_state.confirmed_framework = framework
    bridge = EventBridge()
    bridge.attach()
    timings = PhaseTimings()
    overrides, settings = _llm_overrides()

    with st.status("Generating proposal…", expanded=True) as status:
        st.write("Track A (resource & consortium) and Track B (market "
                 "intelligence) are running concurrently…")
        try:
            res = run_proposal_generation_phase(
                analysis, injected_cvs=st.session_state.injected_cvs,
                bridge=bridge, timings=timings, overrides=overrides,
                settings=settings)
        except Exception as e:                                   # noqa: BLE001
            bridge.detach()
            st.session_state.running = False
            status.update(label="Generation failed", state="error")
            st.error(f"{type(e).__name__}: {e}")
            return
        bridge.detach()
        for ev in bridge.events():
            st.write(ev.message)

        st.session_state.events = [e.as_dict() for e in bridge.history()]
        st.session_state.phase2 = {
            "market": res.market.model_dump() if res.market else None,
            "resources": res.resources.model_dump() if res.resources else None,
            "draft": res.draft.model_dump() if res.draft else None,
            "final": res.final.model_dump() if res.final else None,
            "rendered_cvs": res.rendered_cvs,
            "errors": res.errors,
        }
        st.session_state.timings.update(timings.report())
        status.update(
            label=f"Proposal generated in {timings.phase2_s:.1f}s", state="complete")
    st.session_state.running = False
    st.rerun()


def _llm_overrides() -> tuple[dict[str, str], dict[str, str]]:
    """Read the sidebar's per-account LLM choice into pipeline overrides."""
    overrides: dict[str, str] = {}
    provider = st.session_state.get("llm_provider") or "(default)"
    model = (st.session_state.get("llm_model") or "").strip()
    if provider and provider != "(default)":
        overrides["provider"] = provider
    if model:
        overrides["model"] = model
    return overrides, {}


def render_execution() -> None:
    st.markdown("## 2 · Agent Execution")

    if not st.session_state.phase2 and not st.session_state.events:
        st.info("Nothing has run yet. Analyze a tender, confirm the framework, "
                "then authorize generation.")
        return

    p2 = st.session_state.phase2 or {}
    st.markdown("### Execution lanes")
    st.caption("Track A and Track B run concurrently. Each row is one agent event.")

    lane_names = {"1": "Analysis", "A": "Track A", "B": "Track B",
                  "4": "Drafting", "5": "Review"}
    for lane_key, lane_label in lane_names.items():
        lane_events = [e for e in st.session_state.events if e.get("lane") == lane_key]
        if not lane_events:
            continue
        st.markdown(f"**{lane_label}** — {AGENT_LABEL.get(lane_events[0].get('agent', ''), '')}")
        for e in lane_events:
            icon = {"tool": "🔧", "success": "✅", "warning": "⚠️",
                    "error": "🔴"}.get(e.get("level", ""), "•")
            st.write(f"{icon} {e.get('message', '')}")
            if e.get("detail"):
                st.caption(f"　　{e['detail']}")

    if p2.get("errors"):
        st.error("Errors during the run:")
        for err in p2["errors"]:
            st.write(f"- {err}")

    if st.session_state.timings:
        st.markdown("### Latency")
        t = st.session_state.timings
        c1, c2, c3, c4 = st.columns(4)
        if "phase1_s" in t:
            c1.metric("Phase 1", f"{t['phase1_s']:.1f}s", help="budget 30s")
        if "phase2_actual_s" in t:
            c2.metric("Phase 2", f"{t['phase2_actual_s']:.1f}s", help="budget 90s")
        if "track_a_actual_s" in t:
            c3.metric("Track A", f"{t['track_a_actual_s']:.1f}s")
        if "track_b_actual_s" in t:
            c4.metric("Track B", f"{t['track_b_actual_s']:.1f}s")


# --------------------------------------------------------------------------- #
# Tab 3 — Review
# --------------------------------------------------------------------------- #

def render_review() -> None:
    st.markdown("## 3 · Review & Audit")
    p2 = st.session_state.phase2 or {}
    draft = p2.get("draft")
    final = p2.get("final")

    if not draft:
        st.info("No draft yet.")
        return

    if final:
        c1, c2, c3 = st.columns(3)
        score = final.get("compliance_score")
        verdict = final.get("score_verdict") or "—"
        c1.metric("Compliance score", f"{score}%" if score is not None else "—",
                  help=f"{final.get('criteria_passed')}/{final.get('criteria_total')} mandatory criteria")
        c2.metric("Verdict", verdict)
        c3.metric("Blockers", len(final.get("blockers") or []))

        if final.get("mandays_mismatch"):
            st.warning(
                f"Level-of-effort mismatch: draft states "
                f"{draft.get('stated_total_mandays')} mandays, recomputed "
                f"{final.get('recomputed_total_mandays')}. Fix before submission.")
        if final.get("missing_forms"):
            st.error(f"Missing required forms: {', '.join(final['missing_forms'])}")
        if final.get("statutory_clause_present") is False:
            st.warning("The statutory anti-corruption clause does not appear in the draft.")

        findings = final.get("findings") or []
        if findings:
            st.markdown("### Findings")
            order = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
            for f in sorted(findings, key=lambda x: order.get(x.get("severity", "info"), 9)):
                sev = f.get("severity", "info")
                mark = {"blocker": "🔴", "major": "🟠", "minor": "🟡",
                        "info": "🔵"}.get(sev, "•")
                verified = "" if f.get("verified") else " _(unverified)_"
                st.write(f"{mark} **{sev.upper()}** — {f.get('finding', '')}{verified}")
                if f.get("evidence"):
                    st.caption(f"　　evidence: {f['evidence']}")
        else:
            st.success("No findings recorded.")

    st.divider()
    st.markdown("### Proposal draft")
    st.download_button("⬇ Download proposal (.md)",
                       data=draft.get("full_markdown") or "",
                       file_name="proposal.md", mime="text/markdown",
                       key="dl_md")
    with st.expander("Preview", expanded=False):
        st.markdown(draft.get("full_markdown") or "_empty_")

    if p2.get("rendered_cvs"):
        st.download_button("⬇ Download TECH-6 CVs (.md)",
                           data="\n\n---\n\n".join(p2["rendered_cvs"]),
                           file_name="tech6-cvs.md", mime="text/markdown",
                           key="dl_cvs")

    if st.button("💾 Save proposal to my account", key="save_prop"):
        _save_proposal(draft, final)


def _save_proposal(draft: dict, final: dict | None) -> None:
    client = _client()
    if not client:
        st.error("Not signed in.")
        return
    try:
        row = {
            "user_id": st.session_state.user_id,
            "project_title": (st.session_state.phase1 or {}).get("project_title")
                             or "Untitled tender",
            "client_name": (st.session_state.phase1 or {}).get("client_name") or "",
            "governing_framework": st.session_state.confirmed_framework
                                   or (st.session_state.phase1 or {}).get("detected_framework") or "",
            "raw_rfp_text": st.session_state.phase1_raw or "",
            "compliance_score": int((final or {}).get("compliance_score") or 0),
            "generated_proposal": draft.get("full_markdown") or "",
            "audit_feedback": json.dumps((final or {}).get("findings") or []),
        }
        res = client.table("proposals").insert(row).execute()
        st.session_state.proposal_id = (res.data or [{}])[0].get("id")
        st.success("Saved to your account.")
    except Exception as e:                                       # noqa: BLE001
        st.error(f"Could not save: {e}")


# --------------------------------------------------------------------------- #
# Tab 4 — Admin config
# --------------------------------------------------------------------------- #

def render_admin() -> None:
    st.markdown("## 4 · Configuration")
    st.caption("Provider, model and endpoint for this account. Stored per user, "
               "so one tenant's key never leaks into another's run.")

    from llm.registry import PROVIDERS

    rows = []
    for name, p in sorted(PROVIDERS.items()):
        rows.append({
            "provider": name,
            "default model": p.default_model,
            "base_url": p.base_url,
            "key env": p.api_key_env,
            "key set": "✅" if os.getenv(p.api_key_env) else "—",
            "notes": p.notes or "",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Available model aliases per provider:")
    for name, p in sorted(PROVIDERS.items()):
        st.markdown(f"**{name}** — " + ", ".join(f"`{m}`" for m in sorted(p.models)))

    st.divider()
    st.markdown("### Test a key")
    st.caption("Sends one minimal request. A failure here means every agent run "
               "will fail the same way.")
    provider = st.selectbox("Provider", sorted(PROVIDERS), key="adm_provider")
    key = st.text_input("API key", type="password", key="adm_key")
    model = st.text_input("Model id override (optional)", key="adm_model")
    if st.button("Test", key="adm_test"):
        _test_key(provider, key, model)


def _test_key(provider: str, key: str, model: str) -> None:
    """One live round-trip against the provider, using the given key.

    Deliberately makes a real call: a key can be well-formed and still be
    rejected (wrong plan, revoked, region-blocked), and the whole point of this
    button is to find that out before a run, not during one.
    """
    from llm.client import build_llm

    try:
        llm = build_llm(agent="analyzer", provider=provider,
                        model=model or None, api_key=key or None)
        t0 = time.time()
        out = llm.call("Reply with exactly: OK")
        st.success(f"✅ {provider} responded in {time.time() - t0:.1f}s: "
                   f"{str(out)[:80]}")
    except Exception as e:                                       # noqa: BLE001
        st.error(f"🔴 {type(e).__name__}: {str(e)[:300]}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    render_sidebar()

    if not st.session_state.authed:
        st.title("QuantumCrewBD")
        st.subheader("Autonomous bid production for public procurement")
        st.markdown(
            "Sign in from the sidebar to begin. The platform ingests a tender, "
            "extracts the evaluation framework and pass mark deterministically, "
            "stops at a human checkpoint, then generates a compliant, "
            "donor-format proposal with a compliance audit.")
        st.info("🔒 Multi-tenant: every query is scoped to your account by "
                "Postgres row-level security. Your bench and proposals are "
                "invisible to other tenants.")
        return

    tabs = st.tabs(["1 · Ingest", "2 · Execution", "3 · Review & Audit",
                    "4 · Configuration"])
    with tabs[0]:
        render_ingest()
    with tabs[1]:
        render_execution()
    with tabs[2]:
        render_review()
    with tabs[3]:
        render_admin()


main()
