-- Per-account LLM configuration, including the provider API key.
--
-- Why a column on profiles rather than an env var: the requirement is that a
-- tenant configures their own model/provider/key and the demo key lives on one
-- account (agentqubec@gmail.com) rather than being baked into the deployment.
-- An env var is global, so it can express neither.
--
-- llm_api_key_enc holds a Fernet-encrypted token, NEVER the plaintext key:
--   Fernet(QC_SECRET_KEY).encrypt(api_key.encode()).decode()
-- QC_SECRET_KEY lives in .env (gitignored) and in KeePass as
-- QuantumCrewBD/QC-Secret-Key. Access is gated by the existing
-- profiles RLS policy (auth.uid() = id), and only service_role / the server
-- can read the ciphertext at all.
--
-- Naming llm_api_key_enc (not llm_api_key) is deliberate: a future reader
-- must not mistake the column for a plaintext secret.
--
-- Rollback:
--   ALTER TABLE public.profiles
--       DROP COLUMN IF EXISTS llm_provider,
--       DROP COLUMN IF EXISTS llm_model,
--       DROP COLUMN IF EXISTS llm_api_key_enc;

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS llm_provider  text,
    ADD COLUMN IF NOT EXISTS llm_model     text,
    ADD COLUMN IF NOT EXISTS llm_api_key_enc text;

COMMENT ON COLUMN public.profiles.llm_api_key_enc IS
    'Fernet-encrypted provider API key (QC_SECRET_KEY). Never plaintext.';
