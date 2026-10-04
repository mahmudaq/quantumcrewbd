"""Per-account LLM configuration: provider, model, and an encrypted API key.

The API key is stored Fernet-encrypted in ``public.profiles.llm_api_key_enc``.
This module is the ONLY place that decrypts it — nothing else in the codebase
should read that column, so the plaintext key has exactly one exit.

The pure helpers (``encrypt_api_key`` / ``decrypt_api_key``) take the secret as
an argument, which is what lets the tests exercise the crypto without a live
database or environment.

Never log, print, or return the plaintext key beyond handing it to the LLM
client.
"""

from __future__ import annotations

import os

ENV_VAR = "QC_SECRET_KEY"
COLUMNS = ("llm_provider", "llm_model", "llm_api_key_enc")


class MissingSecretKeyError(RuntimeError):
    """``QC_SECRET_KEY`` is absent or not a usable Fernet key."""


def _fernet(secret: str | None = None):
    value = (secret or os.getenv(ENV_VAR) or "").strip()
    if not value:
        raise MissingSecretKeyError(
            f"{ENV_VAR} is not set, so per-account API keys cannot be read or "
            "written. Set it in .env (see .env.example) — it is also in KeePass "
            "as QuantumCrewBD/QC-Secret-Key."
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(value.encode())
    except Exception as exc:  # noqa: BLE001 - any malformed key lands here
        raise MissingSecretKeyError(f"{ENV_VAR} is not a valid Fernet key: {exc}") from exc


def encrypt_api_key(plaintext: str, *, secret: str | None = None) -> str:
    """Encrypt an API key for storage. Refuses an empty value on purpose."""
    if not plaintext or not plaintext.strip():
        raise ValueError("refusing to encrypt an empty API key")
    return _fernet(secret).encrypt(plaintext.strip().encode()).decode()


def decrypt_api_key(token: str, *, secret: str | None = None) -> str:
    """Decrypt a stored API key. Raises on the wrong secret or a corrupt value."""
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except MissingSecretKeyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "could not decrypt the stored API key — is QC_SECRET_KEY the same one "
            "that encrypted it?"
        ) from exc


def load_account_llm(client, user_id: str, *, secret: str | None = None) -> dict:
    """Read one account's LLM config. Never raises: a demo must not die here.

    ``secret`` defaults to ``QC_SECRET_KEY``; it is a parameter so the crypto can
    be exercised without depending on ambient environment.
    Returns keys: ``provider``, ``model``, ``api_key`` (plaintext or None), and
    ``key_error`` when a stored key exists but cannot be decrypted.
    """
    if client is None or not user_id:
        return {}
    try:
        rows = (
            client.table("profiles")
            .select(",".join(COLUMNS))
            .eq("id", user_id)
            .limit(1)
            .execute()
            .data
        ) or []
    except Exception:  # noqa: BLE001 - missing row / transient network error
        return {}
    if not rows:
        return {}

    row = rows[0]
    out: dict = {
        "provider": row.get("llm_provider") or None,
        "model": row.get("llm_model") or None,
        "api_key": None,
    }
    enc = row.get("llm_api_key_enc")
    if enc:
        try:
            out["api_key"] = decrypt_api_key(enc, secret=secret)
        except Exception:  # noqa: BLE001
            # A wrong QC_SECRET_KEY (e.g. after a redeploy) must degrade to
            # "no key configured", not crash the page — the user can re-enter it.
            out["api_key"] = None
            out["key_error"] = "stored key could not be decrypted — re-enter it"
    return out


def save_account_llm(
    client,
    user_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    secret: str | None = None,
) -> dict:
    """Persist this account's LLM config and return the columns written.

    ``api_key`` semantics are deliberate:
      * ``None``  -> leave any stored key untouched (editing provider only)
      * ``""``    -> clear the stored key
      * ``"abc"`` -> encrypt and replace
    """
    if client is None or not user_id:
        raise ValueError("a client and user_id are required")

    payload: dict = {}
    if provider is not None:
        payload["llm_provider"] = provider or None
    if model is not None:
        payload["llm_model"] = model or None
    if api_key is not None:
        payload["llm_api_key_enc"] = (
            encrypt_api_key(api_key, secret=secret) if api_key else None
        )
    if not payload:
        return {}

    client.table("profiles").update(payload).eq("id", user_id).execute()
    return payload
