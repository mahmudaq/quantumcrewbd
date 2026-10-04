"""Prove tenant isolation holds for a genuinely anonymous client.

The subtlety this exists to catch: `get_supabase_client()` returns a SINGLETON.
Calling sign_in_with_password() on it attaches the user's JWT, so the "anon"
client silently becomes an *authenticated* one and happily reads that user's
rows. A naive isolation test then either false-alarms (like ours did) or, worse,
false-passes. This uses a fresh client that never signs in.
"""

import os
import sys

sys.path.insert(0, "/app")   # or the repo root when run locally

from supabase import create_client

from database.supabase_client import get_supabase_client, get_user_client

URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]
email = os.environ.get("QC_TEST_EMAIL", "personal.assistant.aq1@gmail.com")
password = os.environ["QC_TEST_PASSWORD"]

fails = []
def check(label, ok, detail=""):
    print(f"  {'OK ' if ok else 'BAD'} {label}{'  -- ' + str(detail)[:150] if detail and not ok else ''}")
    if not ok: fails.append(label)

print("=" * 70)
print("  Tenant isolation — anon role must see nothing")
print("=" * 70)

# Authenticated owner inserts a row.
auth = get_supabase_client()
s = auth.auth.sign_in_with_password({"email": email, "password": password})
token, uid = s.session.access_token, s.user.id
owner = get_user_client(token)
res = owner.table("team_cvs").insert({
    "user_id": uid, "full_name": "RLS Probe", "current_role": "Probe",
    "years_experience": 1, "certifications": [], "skills": [],
    "cv_summary": "isolation probe",
}).execute()
row_id = res.data[0]["id"]
check("owner inserted a probe row", bool(row_id))

# A client that has NEVER signed in — nothing but the anon key.
anon = create_client(URL, ANON)
try:
    rows = anon.table("team_cvs").select("id,full_name").execute().data or []
    check("anon SELECT returns 0 rows", len(rows) == 0, f"saw {len(rows)}")
except Exception as exc:
    check("anon SELECT returns 0 rows", True, f"raised (acceptable): {exc}")

try:
    anon.table("team_cvs").insert({
        "user_id": uid, "full_name": "Anon Intruder", "current_role": "x",
        "years_experience": 0, "certifications": [], "skills": [],
        "cv_summary": "should be rejected",
    }).execute()
    check("anon INSERT is rejected", False, "anon managed to insert!")
except Exception:
    check("anon INSERT is rejected", True)

try:
    anon.table("team_cvs").delete().eq("id", row_id).execute()
    still = owner.table("team_cvs").select("id").eq("id", row_id).execute().data or []
    check("anon DELETE cannot remove the row", len(still) == 1,
          "row was deleted by anon")
except Exception:
    check("anon DELETE cannot remove the row", True)

# Owner can still see their own row (the policy is not simply denying all).
mine = owner.table("team_cvs").select("id").eq("id", row_id).execute().data or []
check("owner still sees their own row", len(mine) == 1)

owner.table("team_cvs").delete().eq("id", row_id).execute()
check("cleanup done",
      len(owner.table("team_cvs").select("id").eq("id", row_id).execute().data or []) == 0)

print("-" * 70)
print(f"  {'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
for f in fails: print(f"    - {f}")
print("=" * 70)
sys.exit(1 if fails else 0)

# --------------------------------------------------------------------------- #
# Why this is a separate script, and not part of the app's own test suite:
#
# `get_supabase_client()` is a module-level SINGLETON. Any test that signs in on
# it and then treats the same object as "the anonymous client" is testing the
# wrong thing — the JWT is already attached, so it will happily return that
# user's rows. That is how our first isolation check produced a false alarm.
#
# This script therefore constructs an entirely separate client from the anon key
# and never signs in on it.
# --------------------------------------------------------------------------- #
