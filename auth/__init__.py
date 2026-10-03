"""Authentication: sign-up, sign-in, and bot protection."""

from auth.flow import (
    AuthOutcome,
    CaptchaConfig,
    SignUpResult,
    captcha_config,
    classify_auth_error,
    password_problem,
    sign_in,
    sign_up,
)

__all__ = [
    "AuthOutcome",
    "CaptchaConfig",
    "SignUpResult",
    "captcha_config",
    "classify_auth_error",
    "password_problem",
    "sign_in",
    "sign_up",
]
