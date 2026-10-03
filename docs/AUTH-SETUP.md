# Authentication setup

The app ships with working sign-in and sign-up. These steps are what turn a
local checkout into a defensible public deployment.

## 1. Sign-up is on by default

`supabase.auth.sign_up` creates accounts. On a public URL that is intentional —
a lockout posture on a public demo means the first person to find the page is
the only one who can use it.

Supabase's own **Confirm email** setting is what gates access, not the UI. Leave
it enabled: sign-up then creates a user who cannot sign in until they follow the
link in their inbox.

## 2. Bot protection (hCaptcha)

Without it, a public sign-up form is a free inbox-filling service, and every
attempt consumes Supabase's project-wide confirmation-email allowance.

**Two independent halves — the second one is the actual control:**

| Half | Where | What it does |
|---|---|---|
| The widget | Browser, `HCAPTCHA_SITE_KEY` | Makes a human complete a challenge |
| The verification | Supabase servers, `HCAPTCHA_SECRET` | Rejects any token that did not come from a real challenge |

A client that skips the widget does not bypass the check — it just has no token,
and Supabase rejects it. That is why the secret must never reach the browser: it
is the only thing that makes the token trustworthy.

### Setup

1. Create a site at <https://dashboard.hcaptcha.com>. Add the deployment
   hostname to its allowed domains.
2. Copy the **site key** to `HCAPTCHA_SITE_KEY` and the **secret** to
   `HCAPTCHA_SECRET`.
3. In the Supabase dashboard: **Authentication → Attack Protection → Enable
   CAPTCHA**, provider **hCaptcha**, and paste the same secret.

Until step 3 is done, the widget renders and the token is sent, but Supabase
does not verify it — the local gate in `auth/flow.py` is all that is active.

### Testing without an hCaptcha account

hCaptcha publishes a key pair that always passes. Both halves must be the test
pair, since Supabase verifies the secret:

```bash
export HCAPTCHA_SITE_KEY=10000000-ffff-ffff-ffff-000000000001
export HCAPTCHA_SECRET=0x0000000000000000000000000000000000000000
curl -s -X PATCH -H "Authorization: Bearer $SUPABASE_PAT" \
  -H "Content-Type: application/json" \
  -d '{"security_captcha_enabled":true,"security_captcha_provider":"hcaptcha",
       "security_captcha_secret":"0x0000000000000000000000000000000000000000"}' \
  https://api.supabase.com/v1/projects/<ref>/config/auth
```

`captcha_config().using_test_keys` reports when the test pair is in use, so a
demo cannot silently be mistaken for a hardened deployment.

## 3. Email rate limit — raised, and why

The Supabase default is **2 confirmation emails per hour, project-wide**. On a
shared project that is exhausted in minutes once more than a couple of people
try to register, and the third person sees a success message and receives
nothing.

Raising it via the Management API requires **custom SMTP** configured:

```
{"message":"Custom SMTP required to configure SMTP_RATE_LIMIT_EMAIL_SENT.
 Missing SMTP_ADMIN_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS."}
```

So there are two options:

| Option | Trade-off |
|---|---|
| Configure custom SMTP, then raise the limit | Removes the ceiling; needs an SMTP provider |
| Keep the default | Works out of the box; roughly two sign-ups per hour |

For a judged demo, **pre-create the accounts the demo will use** and sign in
rather than signing up live. That sidesteps the limit entirely and removes a
network dependency from the critical path.

## 4. What the app deliberately does not do

- **No account-existence oracle.** Sign-up answers with one shared constant
  (`SIGNUP_UNIFORM_MESSAGE`) whether or not the address already existed.
  Otherwise the public form doubles as an account enumeration endpoint. Covered
  by `tests/test_auth_flow.py::TestNoAccountExistenceOracle`.
- **No `service_role` key in the app.** It bypasses RLS entirely. The app uses
  the anon key plus the signed-in user's JWT, so row-level security is what
  actually isolates tenants — not application code.
- **No CAPTCHA secret in the browser.** Only `site_key` is rendered; a test
  asserts the app never emits the secret.
