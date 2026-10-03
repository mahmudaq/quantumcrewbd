"""Authoritative UI verification: run the real app.py through Streamlit's harness.

A screenshot can be blank for harness reasons (websocket handshake) and a
healthcheck cannot tell a rendered page from a broken one. AppTest executes
app.py exactly as the server does and reports real exceptions.

Run INSIDE the container so it verifies the deployed artifact, not the source tree.
"""
from __future__ import annotations

import sys
import traceback

sys.path.insert(0, "/app")

from streamlit.testing.v1 import AppTest  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✅" if cond else "🔴"
    print(f"  {mark} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(name)


print("=" * 74)
print("QUANTUMCREWBD UI VERIFICATION (Streamlit AppTest, inside the container)")
print("=" * 74)

# ---------------------------------------------------------------- render
print("\n[1] Unauthenticated render — the login gate")
print("-" * 74)
try:
    at = AppTest.from_file("/app/app.py", default_timeout=120)
    at.run()
except Exception:
    print("  🔴 AppTest could not run app.py")
    traceback.print_exc()
    raise SystemExit(1)

if at.exception:
    print("  🔴 app.py raised during render:")
    for e in at.exception:
        print(f"     {type(e.value).__name__}: {e.value}")
    FAILURES.append("render raised")
else:
    check("app.py renders without exception", True)

# ---------------------------------------------------------------- tabs
print("\n[2] Auth surface is present")
print("-" * 74)
tab_labels = [t.label for t in at.tabs] if hasattr(at, "tabs") else []
print(f"    tabs: {tab_labels}")
check("sign-in and sign-up surfaces exist",
      any("ign" in l for l in tab_labels) and any("reate" in l or "ign up" in l for l in tab_labels),
      f"{tab_labels}")

# ---------------------------------------------------------------- widget inventory
print("\n[3] Form widgets are wired")
print("-" * 74)
all_boxes = list(getattr(at, "text_input", [])) + list(getattr(at, "sidebar", []).text_input)
keys = [b.key for b in all_boxes if getattr(b, "key", None)]
print(f"    text_input keys: {keys}")
check("email field present", any("email" in k for k in keys), f"{keys}")
check("password field present",
      any(k.endswith("_pw") or "password" in k for k in keys), f"{keys}")

buttons = [b.label for b in getattr(at, "button", [])]
sidebar_buttons = [b.label for b in getattr(at, "sidebar", []).button]
print(f"    buttons: {buttons}")
print(f"    sidebar buttons: {sidebar_buttons}")

# ---------------------------------------------------------------- captcha state
print("\n[4] CAPTCHA state is honest about itself")
print("-" * 74)
try:
    from auth.flow import captcha_config
    cfg = captcha_config()
    print(f"    enabled={cfg.enabled}  site_key_set={bool(cfg.site_key)}  "
          f"using_test_keys={cfg.using_test_keys}")
    check("captcha_config() reachable from the deployed image", True)
    # Holding the secret in a server-side dataclass is correct — Supabase needs it
    # to verify the token. The property that matters is that it is never RENDERED.
    import inspect as _inspect
    from streamlit.testing.v1 import AppTest as _AT
    app_src = open("/app/app.py", encoding="utf-8").read()
    render_fn = app_src.split("def _captcha_token")[1].split("\ndef ")[0]
    check("secret is never written into rendered HTML",
          "cfg.secret" not in render_fn and "{cfg.secret}" not in render_fn,
          "only cfg.site_key reaches components.html")
    check("test keys are detectable (so a demo can't masquerade as hardened)",
          hasattr(cfg, "using_test_keys"))
except Exception as e:
    check("captcha_config() reachable", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------------------- sign-in error path
print("\n[5] A wrong password is rejected (not silently accepted)")
print("-" * 74)
try:
    from auth.flow import sign_in
    # Deliberately wrong credentials against the real Supabase project.
    from database.supabase_client import get_supabase_client
    client = get_supabase_client()
    if client is None:
        print("    ⚠️  Supabase client unavailable — skipping live auth check")
    else:
        out = sign_in("nobody-here@invalid-domain-qc.test", "wrong-password-xyz",
                      captcha_token=None, client=client)
        print(f"    ok={out.ok}  kind={out.kind}  message={out.message[:70]!r}")
        check("bad credentials are rejected", out.ok is False)
        check("error does not confirm whether the account exists",
              "not found" not in out.message.lower() and
              "no user" not in out.message.lower(),
              out.message[:70])
except Exception as e:
    check("live sign-in path exercises", False, f"{type(e).__name__}: {e}")

print("\n" + "=" * 74)
if FAILURES:
    print(f"RESULT: 🔴 {len(FAILURES)} CHECK(S) FAILED: {FAILURES}")
    raise SystemExit(1)
print("RESULT: ✅ ALL UI CHECKS PASSED")
