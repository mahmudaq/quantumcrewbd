# UI verification — QuantumCrewBD

Run this after any deploy. A screenshot cannot distinguish "renders correctly"
from "websocket never handshook", and a healthcheck cannot distinguish "serving"
from "serving a page that raises". This exercises the real `app.py` through
Streamlit's own renderer and asserts on what it produces.

## Why AppTest and not a browser screenshot

| Signal | What it actually proves |
|---|---|
| `/_stcore/health` → 200 | The process is up. **Nothing about the page.** |
| Screenshot is blank | Nothing — Streamlit renders over a websocket that headless Chrome may never complete |
| `AppTest` | Executes `app.py` exactly as the server does, and surfaces real Python exceptions |

The Dockerfile bug this caught is the demonstration: `COPY auth/` was missing, so
`from auth.flow import sign_up` raised `ModuleNotFoundError` — but only *inside a
render function*, so the build passed, the healthcheck passed, and the container
reported healthy for 30 minutes while the login page was unrenderable.

**A healthcheck that never renders the page cannot see a render bug.**

## Usage

Run inside the container so it verifies the deployed artifact:

```bash
docker cp /tmp/qa_ui.py quantumcrewbd:/tmp/qa_ui.py
docker exec -u root quantumcrewbd chmod 644 /tmp/qa_ui.py
docker exec quantumcrewbd python /tmp/qa_ui.py
```

Run from the repo, outside the container, to verify the source tree:

```bash
.venv/bin/python scripts/qa_ui.py
```

Exit code is non-zero if any check fails, so it can gate a deploy.

## What it checks

1. **Render** — `app.py` runs with no exception (the check that would have caught
   the missing `COPY auth/`).
2. **Auth surface** — both tabs present.
3. **Widgets** — email/password fields for sign-in and sign-up are wired.
4. **CAPTCHA config** — reachable, and honest about whether test keys are in use.
5. **Live rejection** — a wrong password is rejected with an error that does not
   confirm whether the account exists.

## Known environment limits

- `AppTest` needs the app's env (`SUPABASE_URL`, keys). Run it inside the
  container, which has `.env`, or export the vars first.
- The CAPTCHA widget itself is rendered via `components.html` (an iframe) and is
  not introspectable from `AppTest`. The **server-side** verification is the real
  control; verifying the widget visually needs a browser.
- Check 5 makes a real network call to Supabase. It is designed to fail closed —
  a rejection is the pass condition — so an outage reads as a failure worth
  investigating, not a false pass.
