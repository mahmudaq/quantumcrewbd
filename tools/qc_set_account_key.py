#!/usr/bin/env python3
"""Save a provider API key onto a QuantumCrewBD account.

The demo key belongs on the `agentqubec@gmail.com` account rather than in the
deployment environment, so a judge who signs in with that account gets a working
run. This script does that without a browser.

Reads the provider key from KeePass and the QC_SECRET_KEY from the repo .env, so
it contains no secret itself.

Usage:
    python tools/qc_set_account_key.py --email agentqubec@gmail.com
    python tools/qc_set_account_key.py --email x@y.z --provider groq \
        --model llama-3.3-70b-versatile
    python tools/qc_set_account_key.py --email x@y.z --show      # status only
    python tools/qc_set_account_key.py --email x@y.z --clear     # remove the key
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# provider -> KeePass entry holding that provider's key
KEY_ENTRIES = {
    "commandcode": "/QuantumCrewBD/CommandCodeAI-API-Key",
    "groq": "/QuantumCrewBD/Groq-API-Key",
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def kpass(title: str) -> str:
    """Read a secret by its Password: label — never the first line (that's the title)."""
    out = subprocess.run(["kpass", "show", "--show-password", title],
                         capture_output=True, text=True, timeout=60).stdout
    for line in out.splitlines():
        if line.strip().startswith("Password:"):
            return line.split("Password:", 1)[1].strip()
    raise SystemExit(f"no Password: line in vault entry {title!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--provider", default="commandcode", choices=sorted(KEY_ENTRIES))
    ap.add_argument("--model", default=None)
    ap.add_argument("--show", action="store_true", help="report status, change nothing")
    ap.add_argument("--clear", action="store_true", help="remove the stored key")
    args = ap.parse_args()

    env = load_env()
    url = env.get("SUPABASE_URL") or "https://qukqelcqngvlplayhjtp.supabase.co"
    anon = env.get("SUPABASE_ANON_KEY") or kpass("/QuantumCrewBD/Supabase-anon-key")
    service = kpass("/QuantumCrewBD/Supabase-service_role-key")

    if args.show:
        # Verify via the service role only that a row exists; never print the key.
        from llm.account_keys import COLUMNS  # noqa: F401  (documents intent)
        req = urllib.request.Request(
            f"{url}/rest/v1/profiles?email=eq.{args.email}&select=llm_provider,llm_model,llm_api_key_enc",
            headers={"apikey": service, "Authorization": f"Bearer {service}",
                     "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            rows = json.loads(resp.read().decode())
        if not rows:
            print(f"no profile row for {args.email}")
            return 1
        row = rows[0]
        print(f"  provider : {row.get('llm_provider') or '(default)'}")
        print(f"  model    : {row.get('llm_model') or '(default)'}")
        print(f"  key      : {'set (' + str(len(row['llm_api_key_enc'])) + ' chars ciphertext)' if row.get('llm_api_key_enc') else 'NOT SET'}")
        return 0

    # Locate the profile row (service role, so RLS does not hide it).
    req = urllib.request.Request(
        f"{url}/rest/v1/profiles?email=eq.{args.email}&select=id",
        headers={"apikey": service, "Authorization": f"Bearer {service}",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = json.loads(resp.read().decode())
    if not rows:
        print(f"no profile row for {args.email} — sign the user up first")
        return 1
    user_id = rows[0]["id"]
    print(f"  account: {args.email}  ({user_id[:8]}...)")

    secret = env.get("QC_SECRET_KEY")
    if not secret:
        print("  QC_SECRET_KEY missing from .env — cannot encrypt; aborting")
        return 1

    from llm.account_keys import encrypt_api_key

    plaintext = "" if args.clear else kpass(KEY_ENTRIES[args.provider])
    if not args.clear:
        print(f"  key source: {KEY_ENTRIES[args.provider]} (len={len(plaintext)})")

    payload = {
        "llm_provider": args.provider,
        "llm_model": args.model,
        "llm_api_key_enc": encrypt_api_key(plaintext, secret=secret) if plaintext else None,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{url}/rest/v1/profiles?id=eq.{user_id}", data=body, method="PATCH",
        headers={"apikey": service, "Authorization": f"Bearer {service}",
                 "Content-Type": "application/json", "Prefer": "return=minimal",
                 "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"  PATCH -> HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        print(f"  PATCH failed: HTTP {exc.code} {exc.read().decode()[:200]}")
        return 1

    # Read back and prove it decrypts to what we intended.
    req = urllib.request.Request(
        f"{url}/rest/v1/profiles?email=eq.{args.email}&select=llm_provider,llm_model,llm_api_key_enc",
        headers={"apikey": service, "Authorization": f"Bearer {service}",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        got = json.loads(resp.read().decode())[0]

    from llm.account_keys import decrypt_api_key
    enc = got.get("llm_api_key_enc")
    if args.clear:
        ok = enc is None
        print(f"  read-back: key cleared -> {ok}")
    else:
        ok = bool(enc) and decrypt_api_key(enc, secret=secret) == plaintext
        print(f"  read-back: decrypts to the intended key -> {ok}"
              f"  (never printed; {len(enc or '')} chars ciphertext)")
    print(f"  stored: provider={got.get('llm_provider')} model={got.get('llm_model')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
