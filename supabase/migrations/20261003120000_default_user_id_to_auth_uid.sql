-- Harden tenant ownership: make user_id default to the caller's auth.uid().
--
-- Why: the RLS policy uses `WITH CHECK (auth.uid() = user_id)`. A row inserted
-- without an explicit user_id has user_id = NULL, so the check fails and the
-- insert is rejected with 42501. That is safe (fail-closed) but it means every
-- client must remember to send user_id, and a legitimate insert from a
-- correctly-scoped client fails for a reason that looks nothing like the
-- actual cause.
--
-- Defaulting the column to auth.uid() makes ownership structural: the database
-- stamps it, the client cannot forge it (an explicit mismatched value still
-- fails WITH CHECK), and a forgetful client still succeeds.
--
-- Applied to Supabase project ref qukqelcqngvlplayhjtp via the Management API.

ALTER TABLE public.team_cvs
    ALTER COLUMN user_id SET DEFAULT auth.uid();

ALTER TABLE public.consortium_partners
    ALTER COLUMN user_id SET DEFAULT auth.uid();

ALTER TABLE public.proposals
    ALTER COLUMN user_id SET DEFAULT auth.uid();

-- profiles.id is the primary key and references auth.users(id); it is the same
-- value, so the default is equally correct there and makes the signup trigger
-- unnecessary for the common case.
ALTER TABLE public.profiles
    ALTER COLUMN id SET DEFAULT auth.uid();

-- Verification: as an authenticated user, an insert with no user_id must now
-- succeed and be stamped with that user's id.
--
--   set local role authenticated;
--   select set_config('request.jwt.claims',
--     json_build_object('sub', '<uid>', 'role', 'authenticated')::text, true);
--   insert into public.team_cvs (full_name, cv_summary)
--     values ('default-probe', 'x') returning user_id;
--   -- expected: user_id = '<uid>'
