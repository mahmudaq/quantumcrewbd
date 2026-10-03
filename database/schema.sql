-- ============================================================================
-- QuantumCrewBD — Production Schema
-- ============================================================================
-- Source: docs/01-Received/quantumcrewbd_master_mvp_specification.md §3.1
--
-- Faithful to the supplied specification, with five corrections. Each is marked
-- [FIX-n] so the team can see exactly what departed from the source document and
-- why. See docs/02-Sent/...E2E_Development_Plan_v1.0.0.md §2 for the rationale.
--
-- Multi-tenant isolation model: every tenant table carries `user_id`, RLS is
-- ENABLED, and the single policy is `auth.uid() = user_id` for BOTH USING and
-- WITH CHECK. The WITH CHECK clause is what makes cross-tenant INSERT rejected
-- rather than merely invisible.
--
-- Target: PostgreSQL 17.11 (Supabase, ap-northeast-2).
-- ============================================================================


-- ============================================================================
-- 1. PROFILES TABLE (User Accounts & Tenant Metadata)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    organization_name TEXT DEFAULT 'Quantum Enterprise',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own profile" ON public.profiles;
CREATE POLICY "Users can manage their own profile"
ON public.profiles FOR ALL
TO authenticated
USING (auth.uid() = id)
WITH CHECK (auth.uid() = id);


-- ----------------------------------------------------------------------------
-- Trigger: auto-provision a profile row on signup
-- ----------------------------------------------------------------------------
-- [FIX-1] The source document collapsed this function body onto a single line
--         inside the markdown fence. It is reformatted here; the collapsed form
--         is a readability defect, not a syntax error.
-- [FIX-2] `SET search_path = public` added. Without a pinned search_path a
--         SECURITY DEFINER function resolves unqualified names against the
--         caller's search_path, which is a privilege-escalation vector.
--         Supabase's own database linter flags this as `function_search_path_mutable`.
-- [FIX-3] `ON CONFLICT (id) DO NOTHING` added so the trigger is idempotent. If a
--         profile row already exists (replayed migration, backfill, manual
--         insert) the original body raises a primary-key violation and the
--         entire signup transaction aborts.
-- [FIX-4] `COALESCE(new.email, '')` — for OAuth/phone signups `new.email` is
--         NULL, which violates `email TEXT NOT NULL` and aborts signup.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, email, organization_name)
    VALUES (new.id, COALESCE(new.email, ''), 'Quantum Enterprise')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();


-- ============================================================================
-- 2. TEAM_CVS TABLE (Internal Talent Bench)
-- ============================================================================
-- [FIX-6] `current_role` is a FULLY RESERVED word in PostgreSQL (pg_get_keywords
--         catcode = 'R') because `CURRENT_ROLE` is a niladic SQL function.
--         The source specification uses it unquoted as a column name, so the
--         spec's own DDL FAILS to execute — verified against PG 17.11:
--             ERROR: 42601: syntax error at or near "current_role"
--         Quoted here. The name is retained (rather than renamed to job_title)
--         so the agent contracts and the Streamlit field labels stay aligned
--         with the specification. Every consumer must quote it: `"current_role"`.
CREATE TABLE IF NOT EXISTS public.team_cvs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    "current_role" TEXT NOT NULL,
    years_experience INT NOT NULL DEFAULT 0,
    education TEXT,
    certifications TEXT[] DEFAULT '{}',
    clearance_level TEXT DEFAULT 'None',
    skills TEXT[] DEFAULT '{}',
    languages JSONB DEFAULT '{"English": "Excellent"}'::jsonb,
    cv_summary TEXT NOT NULL,
    past_performance_refs TEXT,
    hourly_rate NUMERIC DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.team_cvs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own talent bench" ON public.team_cvs;
CREATE POLICY "Users can manage their own talent bench"
ON public.team_cvs FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_team_cvs_user ON public.team_cvs(user_id);
CREATE INDEX IF NOT EXISTS idx_team_cvs_role ON public.team_cvs("current_role");

-- [FIX-5] GIN indexes on the array columns actually filtered by the internal
--         search tools (`skills`, `certifications`). Without these every bench
--         search is a sequential scan with an unindexed `&&`/`@>` operator.
CREATE INDEX IF NOT EXISTS idx_team_cvs_skills ON public.team_cvs USING GIN (skills);
CREATE INDEX IF NOT EXISTS idx_team_cvs_certifications ON public.team_cvs USING GIN (certifications);


-- ============================================================================
-- 3. CONSORTIUM_PARTNERS TABLE (Vetted Teaming & Joint Venture Directory)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.consortium_partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    primary_domain TEXT NOT NULL,
    specialties TEXT[] DEFAULT '{}',
    certifications TEXT[] DEFAULT '{}',
    annual_turnover_tier TEXT,
    key_past_performance TEXT NOT NULL,
    point_of_contact_name TEXT,
    point_of_contact_email TEXT,
    website TEXT,
    vetting_status TEXT DEFAULT 'Vetted',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.consortium_partners ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own consortium directory" ON public.consortium_partners;
CREATE POLICY "Users can manage their own consortium directory"
ON public.consortium_partners FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_consortium_user ON public.consortium_partners(user_id);
CREATE INDEX IF NOT EXISTS idx_consortium_domain ON public.consortium_partners(primary_domain);
CREATE INDEX IF NOT EXISTS idx_consortium_specialties ON public.consortium_partners USING GIN (specialties);


-- ============================================================================
-- 4. PROPOSALS TABLE (Audited Dossiers & Bid Runs)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    project_title TEXT NOT NULL,
    client_name TEXT DEFAULT 'Public / Enterprise Tender',
    governing_framework TEXT DEFAULT 'World Bank SPD',
    raw_rfp_text TEXT NOT NULL,
    compliance_score INT DEFAULT 0,
    generated_proposal TEXT NOT NULL,
    audit_feedback TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

ALTER TABLE public.proposals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own proposals" ON public.proposals;
CREATE POLICY "Users can manage their own proposals"
ON public.proposals FOR ALL
TO authenticated
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_proposals_user ON public.proposals(user_id);
CREATE INDEX IF NOT EXISTS idx_proposals_created ON public.proposals(created_at DESC);


-- ============================================================================
-- End of migration. Expected post-conditions:
--   4 tables in schema `public`
--   4 RLS policies (one per table)
--   4 tables with rowsecurity = true
--   1 trigger on auth.users
-- ============================================================================
