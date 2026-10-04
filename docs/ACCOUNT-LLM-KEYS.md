# Per-account LLM keys

Each account stores its own provider, model, and API key. The demo key lives on
one account (`agentqubec@gmail.com`) rather than on the host, so a judge signing
in with that account gets a working run without any setup.

## Why per-account instead of one env var

An env var is global: it can't express "this tenant uses Groq, that one uses
CommandCode", and it puts the demo's key on the server where every account
shares it. Per-account storage is also what the product needs anyway — the
flexible-LLM requirement is per-tenant, not per-deployment.

## How it is stored

| Column | Meaning |
|---|---|
| `profiles.llm_provider` | provider name (`commandcode`, `groq`), or NULL for the default |
| `profiles.llm_model` | model alias or raw id, or NULL for the default |
| `profiles.llm_api_key_enc` | the key, Fernet-encrypted. **Never plaintext.** |

The column is deliberately named `..._enc` so nobody reads it as a plaintext
secret. `llm/account_keys.py` is the only module that decrypts it — one exit for
the plaintext key.

Access is governed by the existing `profiles` RLS policy
(`auth.uid() = id`, role `authenticated`), so one tenant cannot read another's
row.

## The encryption key

`QC_SECRET_KEY` (Fernet, 44 chars) lives in:

- `.env` — gitignored, and **not** in the Docker image (`docker-compose.yml`
  passes it as a runtime variable)
- KeePass — `QuantumCrewBD/QC-Secret-Key`, so it survives losing the server

Generate one:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Losing it is **not** fatal: stored keys become undecryptable, `load_account_llm`
reports "re-enter it", and a run falls back to the deployment key or fails with
a clear message. It never crashes the page.

## Key precedence for a run

1. A key typed into the sidebar for **this run only** (never persisted)
2. The key **saved on the account**
3. The **deployment** env var (`COMMANDCODE_API_KEY` / `GROQ_API_KEY`)

If a key is saved for a *different* provider than the one selected, it is not
used — the fallback applies instead, rather than sending a Groq key to
CommandCode and getting a 401 that looks like an outage.

## Setting the demo key

Sign in as `agentqubec@gmail.com`, open **4 · Configuration**, enter the key,
click **Save to this account**. Or non-interactively:

```bash
python tools/qc_set_account_key.py --email agentqubec@gmail.com
```

The value is read from KeePass (`QuantumCrewBD/CommandCodeAI-API-Key`) so the
script contains no secret.

## Where the model/provider choice is applied

`_llm_overrides()` returns `{"provider", "model"}` keyed at the *global* level,
and `resolve()` (in `llm/registry.py`) reads those keys for every agent. The key
travels to each agent as `settings["api_key"]` — a plain function argument, not a
context variable, because Track A/B run inside a `ThreadPoolExecutor` where a
`ContextVar` set on the main thread would not propagate.
