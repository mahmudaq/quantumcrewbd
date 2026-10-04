"""Verify the bench CV-upload UI renders, using Streamlit's own AppTest.

A screenshot cannot tell "the page rendered the upload widget" from "the page
raised on import", and a Docker healthcheck cannot tell either. AppTest runs the
real ``app.py`` in-process and asserts on the widget tree, so this is the
authoritative check for the Streamlit layer.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/home/agentq/.hermes/profiles/dev-001/projects/QuantumCrewBD/03-Working/repo")

from streamlit.testing.v1 import AppTest  # noqa: E402

PASS, FAIL = [], []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  {'✅' if ok else '🔴'} {label}{'  — ' + detail if detail and not ok else ''}")


print("=" * 70)
print("  Bench CV-upload UI — AppTest against the live app.py")
print("=" * 70)

at = AppTest.from_file("/home/agentq/.hermes/profiles/dev-001/projects/QuantumCrewBD/03-Working/repo/app.py", default_timeout=60)
at.run()

check("app renders without exception", not at.exception,
      str(at.exception[0].value) if at.exception else "")

# Sign-in gate: we expect the auth tabs, not the analysis UI.
tab_labels = [t.label for t in at.tabs] if at.tabs else []
check("auth tabs present", "Sign in" in tab_labels, str(tab_labels))

# Drive a session directly so the bench (behind auth) is reachable. A real
# access token is required: _client() returns None without one, and the bench
# silently renders nothing behind that guard (a QA trap in its own right).
from database.supabase_client import get_supabase_client  # noqa: E402

import os  # noqa: E402

_tokens = {}
env = "/tmp/.qc-tokens.env"
if os.path.exists(env):
    for line in open(env):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            _tokens[k] = v.strip().strip('"').strip("'")

email = os.environ.get("QC_TEST_EMAIL", "personal.assistant.aq1@gmail.com")
# Never hardcode the password: pass it in via the environment. The value lives
# in KeePassXC and in /tmp/qc_make_users.py on this host, not in the repo.
password = os.environ.get("QC_TEST_PASSWORD", "")
client = get_supabase_client()
session = client.auth.sign_in_with_password({"email": email, "password": password})
at.session_state["authed"] = True
at.session_state["access_token"] = session.session.access_token
at.session_state["user_id"] = session.user.id
at.session_state["user_email"] = session.user.email
at.run()

check("no exception with a session", not at.exception,
      str(at.exception[0].value) if at.exception else "")

# The bench lives in the sidebar; find the upload/typing selector.
radios = [r for r in at.radio] if at.radio else []
mode_opts = [o for r in radios for o in (r.options or [])]
check("bench mode selector present",
      any("Uploading a CV" in str(o) for o in mode_opts), str(mode_opts))

up = at.get("file_uploader") if hasattr(at, "get") else []
check("CV file uploader renders", bool(up),
      "no file_uploader widget found")

# Switch to manual typing and confirm that path still works.
try:
    at.radio(key="cv_mode").set_value("Typing details").run()
    check("manual entry path still renders", not at.exception,
          str(at.exception[0].value) if at.exception else "")
    manual = [i for i in at.text_input if i.key == "cv_name"]
    check("manual name field present", bool(manual))
except Exception as exc:                                          # noqa: BLE001
    check("manual entry path still renders", False, str(exc))

print("-" * 70)
print(f"  PASS {len(PASS)}   FAIL {len(FAIL)}")
if FAIL:
    print("  failures:")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
