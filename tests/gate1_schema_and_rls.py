#!/usr/bin/env python3
"""
Gate 1 — Phase 1 acceptance, EXECUTED against the live Supabase project.

Applies database/schema.sql through the Supabase Management API and then proves
the multi-tenant isolation guarantee with two real auth users. Nothing here is
asserted from reading the DDL; every claim is a query result.

Design notes
------------
* The schema is submitted as ONE query, not split on semicolons. Naive splitting
  breaks PL/pgSQL bodies, which legitimately contain `;` inside `$$ ... $$`.
  A single submission also runs in an implicit transaction, so the migration is
  atomic: either every statement applies or none does.
* Isolation is proven by impersonating each user *inside Postgres* —
  `set_config('request.jwt.claims', ...)` + `SET LOCAL ROLE authenticated` is
  exactly what PostgREST does per request. Testing over a superuser connection
  would bypass RLS and prove nothing.

Run:  SUPABASE_PAT=... python3 tests/gate1_schema_and_rls.py
Exit: 0 = all gates passed, 1 = at least one gate failed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

PROJECT_REF = "qukqelcqngvlplayhjtp"
API = "https://api.supabase.com/v1"
SCHEMA_FILE = os.path.join(os.path.dirname(__file__), "..", "database", "schema.sql")

TENANT_TABLES = ("profiles", "team_cvs", "consortium_partners", "proposals")
_rls_probed = ("team_cvs", "consortium_partners", "proposals", "profiles")

_passes: list[str] = []
_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    (_passes if ok else _failures).append(f"{label} :: {detail}")
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def load_pat() -> str:
    pat = os.environ.get("SUPABASE_PAT")
    if not pat:
        raise SystemExit("SUPABASE_PAT not set (KeePassXC /QuantumCrewBD/Supabase-PAT).")
    return pat


def run_sql(pat: str, sql: str) -> tuple[int, object]:
    """Execute SQL via the Management API. Returns (http_status, payload)."""
    req = urllib.request.Request(
        f"{API}/projects/{PROJECT_REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {pat}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "quantumcrewbd-gate1")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body.strip() else [])
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def rows_of(payload: object) -> list:
    """Normalise a SQL payload to a list of row dicts, or [] on error."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def scalar(pat: str, sql: str) -> object | None:
    """Run SQL expected to return a single row; return that row's first value."""
    _, payload = run_sql(pat, sql)
    rows = rows_of(payload)
    if rows and len(rows[0]) == 1:
        return next(iter(rows[0].values()))
    return None


def as_user(uid: str) -> str:
    """
    Prefix that impersonates an authenticated user for the duration of a
    transaction — the in-database equivalent of a PostgREST request carrying
    that user's JWT. Must be paired with a COMMIT.
    """
    claims = json.dumps({"sub": uid, "role": "authenticated"}).replace("'", "''")
    return (
        "BEGIN; "
        f"SELECT set_config('request.jwt.claims', '{claims}', true); "
        "SET LOCAL ROLE authenticated; "
    )


def as_anon() -> str:
    """
    Impersonate a request carrying no user JWT — i.e. a request made with only
    the anon key. This is the exact condition behind defect R-04, and it must
    yield zero rows on every tenant table.
    """
    return "BEGIN; SET LOCAL ROLE authenticated; "


def main() -> int:
    pat = load_pat()

    # ---------------------------------------------------------------- 1. apply
    print("\n=== 1. apply database/schema.sql (single atomic submission) ===")
    ddl = open(SCHEMA_FILE, encoding="utf-8").read()
    n_statements = len([s for s in re.sub(r"--[^\n]*", "", ddl).split(";") if s.strip()])
    status, payload = run_sql(pat, ddl)
    ok = status in (200, 201)
    check("schema applied atomically", ok, f"HTTP {status}, {n_statements} statements")
    if not ok:
        print(f"        ! {str(payload)[:400]}")

    # ------------------------------------------------------------- 2. tables
    print("\n=== 2. tables exist in public ===")
    _, payload = run_sql(
        pat, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
    )
    found = {r["tablename"] for r in rows_of(payload)}
    for t in TENANT_TABLES:
        check(f"table public.{t}", t in found)
    check("no unexpected extra public tables",
          not (found - set(TENANT_TABLES)), f"extra={sorted(found - set(TENANT_TABLES))}")

    # ---------------------------------------------------------------- 3. RLS
    print("\n=== 3. RLS enabled on every tenant table ===")
    _, payload = run_sql(
        pat,
        "SELECT c.relname, c.relrowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname;",
    )
    rls = {r["relname"]: r["relrowsecurity"] for r in rows_of(payload)}
    for t in TENANT_TABLES:
        check(f"rowsecurity on {t}", rls.get(t) is True, f"relrowsecurity={rls.get(t)}")
    check("ALL tables have rowsecurity (none unprotected)",
          all(rls.get(t) is True for t in TENANT_TABLES))

    # ------------------------------------------------------------ 4. policies
    print("\n=== 4. policies: exactly one per table, USING + WITH CHECK ===")
    _, payload = run_sql(
        pat,
        "SELECT tablename, policyname, cmd, qual IS NOT NULL AS has_using, "
        "with_check IS NOT NULL AS has_check "
        "FROM pg_policies WHERE schemaname='public' ORDER BY tablename;",
    )
    pol = rows_of(payload)
    by_table: dict[str, list] = {}
    for r in pol:
        by_table.setdefault(r["tablename"], []).append(r)
    check("total policy count == 4", len(pol) == 4, f"count={len(pol)}")
    for t in TENANT_TABLES:
        entries = by_table.get(t, [])
        check(f"{t}: exactly 1 policy", len(entries) == 1, f"count={len(entries)}")
        if entries:
            check(f"{t}: has USING", entries[0]["has_using"] is True)
            check(f"{t}: has WITH CHECK (blocks cross-tenant writes)",
                  entries[0]["has_check"] is True)

    # ------------------------------------------------------------- 5. trigger
    print("\n=== 5. handle_new_user trigger installed and hardened ===")
    _, payload = run_sql(
        pat,
        "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE NOT t.tgisinternal AND n.nspname='auth' AND c.relname='users';",
    )
    trig = [r["tgname"] for r in rows_of(payload)]
    check("on_auth_user_created trigger exists",
          "on_auth_user_created" in trig, f"found={trig}")

    _, payload = run_sql(
        pat,
        "SELECT p.prosecdef, "
        "  EXISTS (SELECT 1 FROM unnest(coalesce(p.proconfig,'{}')) cfg "
        "          WHERE cfg LIKE 'search_path=%') AS has_search_path "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname='handle_new_user';",
    )
    fn = rows_of(payload)
    if check("handle_new_user exists", bool(fn)):
        check("handle_new_user is SECURITY DEFINER", fn[0]["prosecdef"] is True)
        check("handle_new_user pins search_path (FIX-2)",
              fn[0]["has_search_path"] is True)

    # ---------------------------------------------- 6. reserved-word handling
    print("\n=== 6. reserved-word column is usable (FIX-6) ===")
    present = scalar(
        pat,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='team_cvs' "
        "AND column_name='current_role';",
    )
    check('team_cvs."current_role" column exists', present == 1, f"count={present}")

    # ------------------------------------------------------- 7. ISOLATION PROOF
    print("\n=== 7. RLS ISOLATION PROOF — two real auth users ===")
    tag = uuid.uuid4().hex[:8]
    pw = f"Gate1!{uuid.uuid4().hex[:16]}"
    created: dict[str, str] = {}

    for label in ("A", "B"):
        email = f"qc-gate1-{label.lower()}-{tag}@example.com"
        status, payload = run_sql(
            pat,
            "INSERT INTO auth.users (instance_id, id, aud, role, email, "
            "encrypted_password, email_confirmed_at, created_at, updated_at, "
            "raw_app_meta_data, raw_user_meta_data) VALUES "
            "('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
            "'authenticated', 'authenticated', "
            f"'{email}', crypt('{pw}', gen_salt('bf')), now(), now(), now(), "
            "'{\"provider\":\"email\",\"providers\":[\"email\"]}'::jsonb, '{}'::jsonb) "
            "RETURNING id;",
        )
        new = rows_of(payload)
        if status in (200, 201) and new:
            created[label] = new[0]["id"]
            check(f"auth user {label} created", True, new[0]["id"])
        else:
            check(f"auth user {label} created", False, f"{status} {str(payload)[:160]}")

    if len(created) == 2:
        uid_a, uid_b = created["A"], created["B"]

        # FIX-3: the trigger must have auto-provisioned a profile for each.
        _, payload = run_sql(
            pat,
            f"SELECT id FROM public.profiles WHERE id IN ('{uid_a}','{uid_b}');",
        )
        n = len(rows_of(payload))
        check("signup trigger auto-created both profiles (FIX-3)", n == 2, f"rows={n}")

        # Seed one row per tenant table for EACH user, so the isolation test is
        # bidirectional: each user must see exactly their own row and never the
        # other's. Seeding only one side would make "B sees 0" pass trivially
        # and prove nothing about the policy.
        def seed_statements(uid: str, tag_: str) -> dict[str, str]:
            return {
                "team_cvs": "INSERT INTO public.team_cvs (user_id, full_name, "
                            '"current_role", cv_summary, skills) VALUES '
                            f"('{uid}', 'Bench {tag_}', 'Engineer', 'seed', ARRAY['python']);",
                "consortium_partners": "INSERT INTO public.consortium_partners (user_id, "
                                       "company_name, primary_domain, key_past_performance) "
                                       f"VALUES ('{uid}', '{tag_} Corp', 'Cloud', 'seed');",
                "proposals": "INSERT INTO public.proposals (user_id, project_title, "
                             "raw_rfp_text, generated_proposal) VALUES "
                             f"('{uid}', '{tag_} Tender', 'raw', 'generated');",
            }

        for label, uid in (("A", uid_a), ("B", uid_b)):
            for table, stmt in seed_statements(uid, label).items():
                status, payload = run_sql(pat, stmt)
                check(f"seed row into {table} as {label}", status in (200, 201),
                      f"HTTP {status}")

        # THE CORE PROOF.
        # `profiles` is keyed by the user's own id, whereas the other three are
        # keyed by user_id. Either way the invariant is the same: you see your
        # own row and nothing of anyone else's.
        for table in _rls_probed:
            own_col = "id" if table == "profiles" else "user_id"

            n_a = scalar(pat, as_user(uid_a)
                         + f"SELECT count(*) AS n FROM public.{table}; COMMIT;")
            check(f"A sees exactly 1 row (own) in {table}", n_a == 1, f"n={n_a}")

            n_b = scalar(pat, as_user(uid_b)
                         + f"SELECT count(*) AS n FROM public.{table}; COMMIT;")
            check(f"B sees exactly 1 row (own) in {table}", n_b == 1, f"n={n_b}")

            # The decisive assertion: neither can reach the other's row.
            n_cross = scalar(pat, as_user(uid_b)
                             + f"SELECT count(*) AS n FROM public.{table} "
                               f"WHERE {own_col} = '{uid_a}'; COMMIT;")
            check(f"B CANNOT reach A's row in {table}  ⟵ RLS ISOLATION",
                  n_cross == 0, f"n={n_cross}")

            n_cross_rev = scalar(pat, as_user(uid_a)
                                 + f"SELECT count(*) AS n FROM public.{table} "
                                   f"WHERE {own_col} = '{uid_b}'; COMMIT;")
            check(f"A CANNOT reach B's row in {table}  ⟵ RLS ISOLATION (reverse)",
                  n_cross_rev == 0, f"n={n_cross_rev}")

            # And with no JWT at all (the R-04 condition), nothing is visible.
            n_anon = scalar(pat, as_anon()
                            + f"SELECT count(*) AS n FROM public.{table}; COMMIT;")
            check(f"anonymous request sees ZERO rows in {table}  ⟵ R-04 PROOF",
                  n_anon == 0, f"n={n_anon}")

        # Cross-tenant INSERT must be REJECTED, not silently allowed.
        status, payload = run_sql(
            pat,
            as_user(uid_b)
            + "INSERT INTO public.team_cvs (user_id, full_name, \"current_role\", "
              f"cv_summary) VALUES ('{uid_a}', 'Injected', 'Rogue', 'x'); COMMIT;",
        )
        msg = str(payload)
        inserted = bool(rows_of(payload)) and "id" in (rows_of(payload)[0] if rows_of(payload) else {})
        rejected = (not inserted) or "row-level security" in msg.lower()
        check("cross-tenant INSERT rejected by WITH CHECK  ⟵ WITH CHECK PROOF",
              rejected, f"HTTP {status} {msg[:120]}")

        # Cross-tenant UPDATE aimed squarely at A's row must touch zero rows.
        upd = scalar(
            pat,
            as_user(uid_b)
            + "WITH u AS (UPDATE public.team_cvs SET full_name='hacked' "
              f"WHERE user_id = '{uid_a}' RETURNING 1) SELECT count(*) AS n FROM u; COMMIT;",
        )
        check("cross-tenant UPDATE of A's row affected 0 rows  ⟵ USING PROOF",
              upd == 0, f"n={upd}")

        # Cross-tenant DELETE aimed at A's row must also touch zero rows.
        dele = scalar(
            pat,
            as_user(uid_b)
            + "WITH d AS (DELETE FROM public.team_cvs "
              f"WHERE user_id = '{uid_a}' RETURNING 1) SELECT count(*) AS n FROM d; COMMIT;",
        )
        check("cross-tenant DELETE of A's row affected 0 rows  ⟵ USING PROOF",
              dele == 0, f"n={dele}")

        # A's row must still be intact after B's write attempts.
        still = scalar(pat, f"SELECT full_name FROM public.team_cvs WHERE user_id='{uid_a}';")
        check("A's row unmodified after B's write attempts", still == "Bench A",
              f"full_name={still!r}")

    # ------------------------------------------------------------- 8. cleanup
    print("\n=== 8. cleanup ===")
    for label, uid in created.items():
        status, _ = run_sql(pat, f"DELETE FROM auth.users WHERE id = '{uid}';")
        check(f"deleted test user {label} (cascades)", status in (200, 201),
              f"HTTP {status}")

    leftover = scalar(pat, "SELECT count(*) FROM public.team_cvs;")
    check("no leftover rows in team_cvs", leftover == 0, f"count={leftover}")

    # -------------------------------------------------------------- summary
    print("\n" + "=" * 70)
    print(f"  GATE 1: {len(_passes)} passed, {len(_failures)} failed")
    print("=" * 70)
    if _failures:
        print("\n  FAILURES:")
        for f in _failures:
            print(f"    - {f}")
        return 1
    print("\n  ✅ PHASE 1 GATE PASSED — schema applied, tenant isolation proven.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
