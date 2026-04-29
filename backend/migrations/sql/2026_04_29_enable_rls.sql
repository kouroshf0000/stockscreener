-- Fixes the Supabase advisor `rls_disabled_in_public` warning.
--
-- Apply order:
--   1. Set SUPABASE_SERVICE_ROLE_KEY in the backend env (Render + GitHub Actions
--      secrets) and update backend/app/config.py + backend/app/supabase_client.py
--      to read it. The anon key cannot bypass RLS and would break every write.
--   2. Run this script in the Supabase SQL editor for project stockscreenerproj
--      (ref vdjtggyssnrhmjizsvwz).
--   3. Re-run `get_advisors` (or refresh the dashboard) and confirm the
--      `rls_disabled_in_public` lints are gone.
--
-- After this script runs, the only role that can read or write these tables is
-- service_role (which bypasses RLS by design). anon and authenticated are
-- denied because no policies exist.

alter table if exists public.signals               enable row level security;
alter table if exists public.paper_trades          enable row level security;
alter table if exists public.conviction_screen_runs enable row level security;
alter table if exists public.thirteenf_digest_cache enable row level security;
alter table if exists public.error_logs            enable row level security;
alter table if exists public.loss_analyses         enable row level security;

-- Catch-all: enable RLS on every remaining base table in `public` that still
-- has it disabled. Idempotent — safe to re-run.
do $$
declare
  r record;
begin
  for r in
    select schemaname, tablename
    from pg_tables
    where schemaname = 'public'
      and rowsecurity = false
  loop
    execute format('alter table %I.%I enable row level security',
                   r.schemaname, r.tablename);
  end loop;
end$$;

-- Belt-and-suspenders: explicitly revoke direct table privileges from the
-- public-facing roles. RLS already blocks them with no policies, but revoking
-- privileges removes the table from the PostgREST schema cache for those roles
-- and silences the advisor regardless of policy state.
do $$
declare
  r record;
begin
  for r in
    select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('revoke all on table public.%I from anon, authenticated',
                   r.tablename);
  end loop;
end$$;
