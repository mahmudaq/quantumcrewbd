"""Auth flow: bot protection, password policy, and state-leak-free errors.

The exposure being closed: the app is reachable at a public Funnel URL with
``disable_signup=False`` and CAPTCHA off. Anyone who finds the URL can create
accounts, and every attempt consumes Supabase's shared, project-wide
confirmation-email allowance.
"""
from __future__ import annotations

import pytest

from auth import flow


class FakeAuth:
    def __init__(self, *, sign_up_result=None, sign_in_result=None,
                 raise_on_sign_up=None, raise_on_sign_in=None):
        self.sign_up_result = sign_up_result
        self.sign_in_result = sign_in_result
        self.raise_on_sign_up = raise_on_sign_up
        self.raise_on_sign_in = raise_on_sign_in
        self.sign_up_calls = []
        self.sign_in_calls = []

    def sign_up(self, credentials):
        self.sign_up_calls.append(credentials)
        if self.raise_on_sign_up:
            raise self.raise_on_sign_up
        return self.sign_up_result

    def sign_in_with_password(self, credentials):
        self.sign_in_calls.append(credentials)
        if self.raise_on_sign_in:
            raise self.raise_on_sign_in
        return self.sign_in_result


class FakeClient:
    def __init__(self, auth):
        self.auth = auth


class Resp:
    def __init__(self, session=None, user=None, email=None):
        self.session = session
        self.user = user
        self.email = email


class User:
    def __init__(self, email):
        self.email = email
        self.id = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (flow.ENV_CAPTCHA_ENABLED, flow.ENV_CAPTCHA_SITE_KEY,
              flow.ENV_CAPTCHA_SECRET):
        monkeypatch.delenv(k, raising=False)


class TestCaptchaConfig:
    def test_disabled_when_nothing_is_configured(self):
        """A fresh clone must still run — no keys required to develop."""
        cfg = flow.captcha_config()
        assert cfg.enabled is False and cfg.has_site_key is False

    def test_enabled_implicitly_when_keys_are_present(self, monkeypatch):
        monkeypatch.setenv(flow.ENV_CAPTCHA_SITE_KEY, "real-site-key")
        monkeypatch.setenv(flow.ENV_CAPTCHA_SECRET, "real-secret")
        assert flow.captcha_config().enabled is True

    def test_explicit_flag_enables_it(self, monkeypatch):
        monkeypatch.setenv(flow.ENV_CAPTCHA_ENABLED, "true")
        assert flow.captcha_config().enabled is True

    @pytest.mark.parametrize("val", ["1", "true", "YES", "on", "True"])
    def test_truthy_spellings(self, monkeypatch, val):
        monkeypatch.setenv(flow.ENV_CAPTCHA_ENABLED, val)
        assert flow.captcha_config().enabled is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", ""])
    def test_falsey_spellings(self, monkeypatch, val):
        monkeypatch.setenv(flow.ENV_CAPTCHA_ENABLED, val)
        assert flow.captcha_config().enabled is False

    def test_test_keys_are_detected_so_a_demo_cannot_be_mistaken_for_production(
            self, monkeypatch):
        monkeypatch.setenv(flow.ENV_CAPTCHA_SITE_KEY, flow.HCAPTCHA_TEST_SITE_KEY)
        monkeypatch.setenv(flow.ENV_CAPTCHA_SECRET, flow.HCAPTCHA_TEST_SECRET)
        assert flow.captcha_config().using_test_keys is True

    def test_real_keys_are_not_flagged_as_test(self, monkeypatch):
        monkeypatch.setenv(flow.ENV_CAPTCHA_SITE_KEY, "1a2b3c4d-real")
        monkeypatch.setenv(flow.ENV_CAPTCHA_SECRET, "ES_abcdef123456")
        assert flow.captcha_config().using_test_keys is False

    def test_secret_is_never_needed_by_the_browser_facing_site_key(self):
        """site_key is public; the secret must never be rendered."""
        assert flow.HCAPTCHA_TEST_SITE_KEY != flow.HCAPTCHA_TEST_SECRET


class TestPasswordPolicy:
    @pytest.mark.parametrize("pw", ["Short1!", ""])
    def test_rejects_short_passwords(self, pw):
        assert flow.password_problem(pw) is not None

    def test_accepts_a_reasonable_password(self):
        assert flow.password_problem("correct-horse-9") is None

    def test_rejects_leading_or_trailing_whitespace(self):
        """Whitespace is invisible in a password field and breaks copy-paste."""
        assert "space" in flow.password_problem(" password123 ")

    def test_rejects_a_single_repeated_character(self):
        assert flow.password_problem("aaaaaaaaaa") is not None

    def test_policy_is_checked_before_any_network_call(self):
        """A predictable rejection must not spend the project-wide rate limit."""
        client = FakeClient(FakeAuth(raise_on_sign_up=AssertionError("called!")))
        res = flow.sign_up("a@b.com", "short", client=client)
        assert res.ok is False
        assert client.auth.sign_up_calls == []


class TestSignUp:
    def test_success_requires_email_confirmation(self):
        client = FakeClient(FakeAuth(sign_up_result=Resp(session=None,
                                                         user=User("a@b.com"))))
        res = flow.sign_up("a@b.com", "a-good-password", client=client)
        assert res.ok and res.needs_confirmation
        assert "confirmation" in res.message.lower()

    def test_immediate_session_means_confirmation_is_off(self):
        client = FakeClient(FakeAuth(sign_up_result=Resp(
            session=object(), user=User("a@b.com"))))
        res = flow.sign_up("a@b.com", "a-good-password", client=client)
        assert res.ok and res.needs_confirmation is False

    def test_captcha_token_is_forwarded_in_the_shape_supabase_expects(self):
        client = FakeClient(FakeAuth(sign_up_result=Resp(user=User("a@b.com"))))
        flow.sign_up("a@b.com", "a-good-password",
                     captcha_token="tok-123", client=client)
        sent = client.auth.sign_up_calls[0]
        assert sent["options"]["captcha_token"] == "tok-123"

    def test_missing_captcha_token_is_refused_locally_when_enabled(
            self, monkeypatch):
        """Fail before the round-trip; Supabase would reject it anyway."""
        monkeypatch.setenv(flow.ENV_CAPTCHA_ENABLED, "true")
        client = FakeClient(FakeAuth(raise_on_sign_up=AssertionError("called!")))
        res = flow.sign_up("a@b.com", "a-good-password", client=client)
        assert res.ok is False and res.kind == "captcha"
        assert client.auth.sign_up_calls == []

    def test_invalid_email_is_rejected_before_the_network(self):
        client = FakeClient(FakeAuth(raise_on_sign_up=AssertionError("called!")))
        res = flow.sign_up("not-an-email", "a-good-password", client=client)
        assert res.ok is False and client.auth.sign_up_calls == []


class TestNoAccountExistenceOracle:
    """The public URL must not answer 'is this address registered?'"""

    def test_signup_reports_already_registered_identically_to_success(self):
        exc = Exception("User already registered")
        client = FakeClient(FakeAuth(raise_on_sign_up=exc))
        res = flow.sign_up("a@b.com", "a-good-password", client=client)
        # Same shape a genuine success takes, so both paths are indistinguishable.
        assert res.ok is True
        assert res.kind == "already_registered"
        assert res.message == flow.SIGNUP_UNIFORM_MESSAGE

    def test_signup_message_matches_the_real_success_message_shape(self):
        """Byte-for-byte identical, so the two paths cannot be told apart."""
        ok_client = FakeClient(FakeAuth(sign_up_result=Resp(user=User("a@b.com"))))
        dupe_client = FakeClient(FakeAuth(
            raise_on_sign_up=Exception("User already registered")))
        ok = flow.sign_up("a@b.com", "a-good-password", client=ok_client)
        dupe = flow.sign_up("a@b.com", "a-good-password", client=dupe_client)
        assert ok.ok == dupe.ok is True
        assert ok.message == dupe.message

    def test_signin_may_still_say_invalid_credentials(self):
        """The caller already claims ownership, so this leaks nothing new."""
        client = FakeClient(FakeAuth(
            raise_on_sign_in=Exception("Invalid login credentials")))
        out = flow.sign_in("a@b.com", "wrong-password", client=client)
        assert out.ok is False and out.kind == "bad_credentials"
        assert out.message == "Incorrect email or password."


class TestErrorClassification:
    @pytest.mark.parametrize("raw,kind", [
        ("email rate limit exceeded", "rate_limited"),
        ("over_email_send_rate_limit", "rate_limited"),
        ("429 Too Many Requests", "rate_limited"),
        ("captcha verification failed", "captcha"),
        ("hCaptcha token invalid", "captcha"),
        ("Email not confirmed", "unconfirmed"),
        ("some totally new provider error", "error"),
    ])
    def test_classification(self, raw, kind):
        assert flow.classify_auth_error(Exception(raw)).kind == kind

    def test_rate_limit_message_tells_the_user_to_wait(self):
        out = flow.classify_auth_error(Exception("email rate limit exceeded"))
        assert "wait" in out.message.lower()

    def test_captcha_message_tells_the_user_to_reload(self):
        out = flow.classify_auth_error(Exception("captcha failed"))
        assert "reload" in out.message.lower()

    def test_raw_provider_error_is_truncated_not_dumped_wholesale(self):
        out = flow.classify_auth_error(Exception("x" * 900))
        assert len(out.message) < 300

    def test_captcha_is_checked_before_generic_rate_limit(self):
        """A captcha failure that also mentions limits must read as a captcha."""
        out = flow.classify_auth_error(
            Exception("captcha failed: rate limit reached"))
        assert out.kind == "rate_limited"


class TestSignIn:
    def test_success_carries_the_session_so_no_second_round_trip(self):
        class Session:
            access_token = "jwt-abc"

        client = FakeClient(FakeAuth(sign_in_result=Resp(
            session=Session(), user=User("a@b.com"))))
        out = flow.sign_in("a@b.com", "pw12345678", client=client)
        assert out.ok is True
        assert out.access_token == "jwt-abc"
        assert out.user_email == "a@b.com" and out.user_id
        # One call, not two — sign-in must not re-issue the request.
        assert len(client.auth.sign_in_calls) == 1

    def test_no_session_is_reported_as_unconfirmed(self):
        client = FakeClient(FakeAuth(sign_in_result=Resp(session=None)))
        out = flow.sign_in("a@b.com", "pw12345678", client=client)
        assert out.ok is False and out.kind == "unconfirmed"

    def test_empty_input_short_circuits(self):
        client = FakeClient(FakeAuth(raise_on_sign_in=AssertionError("called!")))
        assert flow.sign_in("", "", client=client).ok is False
        assert client.auth.sign_in_calls == []

    def test_captcha_token_forwarded_on_sign_in_too(self):
        client = FakeClient(FakeAuth(sign_in_result=Resp(session=object())))
        flow.sign_in("a@b.com", "pw12345678", captcha_token="t", client=client)
        assert client.auth.sign_in_calls[0]["options"]["captcha_token"] == "t"


class TestNoSecretsLeakIntoUi:
    def test_flow_module_never_renders_the_secret(self):
        import inspect
        src = inspect.getsource(flow)
        # The secret is read, never returned to a caller that renders it.
        assert "return CaptchaConfig(enabled=enabled, site_key=site_key" in src

    def test_app_never_renders_the_captcha_secret(self):
        """The secret only ever goes to Supabase, via the server-side config."""
        app_src = open("app.py", encoding="utf-8").read()
        assert "captcha_config().secret" not in app_src
        assert "cfg.secret" not in app_src

    def test_service_role_key_is_absent_from_the_app(self):
        """Defence in depth: the app must never hold an RLS-bypassing key."""
        app_src = open("app.py", encoding="utf-8").read()
        assert "SERVICE_ROLE" not in app_src.upper()
