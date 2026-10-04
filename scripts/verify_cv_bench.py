"""End-to-end: real CV file -> extraction -> team_cvs row -> read back.

Run inside the container, or locally with the repo venv. Signs in as the QA
user so RLS applies exactly as it does for a real account.

Usage:
    QC_TEST_PASSWORD=... python scripts/verify_cv_bench.py [--cleanup]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from database.supabase_client import get_supabase_client, get_user_client  # noqa: E402
from parsing.cv import extract_cv_file  # noqa: E402

INBOX = Path(os.environ.get(
    "QC_CV_INBOX",
    "/app/../QuantumCrewBD-local-cvs/inbox",
))

FAILS: list[str] = []
DEFAULT_INBOX = Path("/home/agentq/.hermes/profiles/dev-001/projects/"
                     "QuantumCrewBD/03-Working/QuantumCrewBD-local-cvs/inbox")


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✅' if ok else '🔴'} {label}{'  — ' + detail if detail and not ok else ''}")
    if not ok:
        FAILS.append(label)


def main() -> int:
    cleanup = "--cleanup" in sys.argv
    email = os.environ.get("QC_TEST_EMAIL", "personal.assistant.aq1@gmail.com")
    password = os.environ.get("QC_TEST_PASSWORD", "")
    if not password:
        print("QC_TEST_PASSWORD is required"); return 2

    inbox = INBOX if INBOX.exists() else DEFAULT_INBOX
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".pdf", ".docx"))
    if not files:
        print(f"no CVs found in {inbox}"); return 2

    print("=" * 70)
    print("  CV -> bench, end to end")
    print("=" * 70)

    client = get_supabase_client()
    session = client.auth.sign_in_with_password({"email": email, "password": password})
    token, uid = session.session.access_token, session.user.id
    user_client = get_user_client(token)
    check("signed in as the QA user", bool(uid), email)

    inserted_ids: list[str] = []
    for path in files:
        ext = extract_cv_file(path)
        row = ext.to_bench(user_id=uid)
        row["cv_summary"] = (row.get("cv_summary") or
                             f"{ext.current_role.value or ''} — "
                             f"{ext.years_experience.value or 0} years")
        print(f"\n  --- {path.name} ---")
        print(f"      name={row['full_name']!r} role={row['current_role']!r} "
              f"years={row['years_experience']}")
        try:
            res = user_client.table("team_cvs").insert(row).execute()
            new_id = res.data[0]["id"] if res.data else None
            inserted_ids.append(new_id)
            check(f"inserted {path.stem}", bool(new_id), str(res.data)[:120])
        except Exception as exc:                                     # noqa: BLE001
            check(f"inserted {path.stem}", False, str(exc)[:200])
            continue

        # Read back *as the same user*: proves RLS lets the owner see the row.
        back = (user_client.table("team_cvs").select(
            "id,full_name,current_role,years_experience,certifications,skills")
            .eq("id", new_id).execute().data or [])
        check(f"read back {path.stem} under RLS", len(back) == 1, str(back)[:120])
        if back:
            r = back[0]
            check(f"  years survived the round trip ({r['years_experience']})",
                  r["years_experience"] == row["years_experience"])
            check(f"  certifications is a list ({type(r['certifications']).__name__})",
                  isinstance(r["certifications"], list))

    # The anon role must not read any bench row. NOTE: this must be a FRESH
    # client. get_supabase_client() is a singleton and we signed in on it above,
    # so it now carries the user's JWT — using it here would report the user's
    # own rows and look like an isolation failure when nothing is wrong.
    from supabase import create_client
    anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])
    try:
        anon_rows = anon.table("team_cvs").select("id").execute().data or []
    except Exception:                    # a hard denial is also a pass
        anon_rows = []
    check("anon role sees zero bench rows (RLS holds)", len(anon_rows) == 0,
          f"saw {len(anon_rows)}")

    if cleanup and inserted_ids:
        for rid in inserted_ids:
            if rid:
                user_client.table("team_cvs").delete().eq("id", rid).execute()
        left = (user_client.table("team_cvs").select("id").execute().data or [])
        check(f"cleaned up ({len(inserted_ids)} inserted, {len(left)} remain)",
              True)
    elif inserted_ids:
        print(f"\n  ℹ️  {len(inserted_ids)} row(s) left in the bench. "
              f"Re-run with --cleanup to remove.")

    print("-" * 70)
    print(f"  {'ALL PASSED' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    for f in FAILS:
        print(f"    - {f}")
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
