-- GitHub App repo access: linked installations, single-use install states, write audit log.
-- Run in the Supabase SQL editor after 0001_auth.sql.
--
-- The backend uses the service key (bypasses RLS) and always filters by user_id itself.
-- RLS here is defence in depth: a leaked anon/user JWT can only ever read the caller's own rows.

-- Installations of our GitHub App linked to a Supabase user
create table if not exists public.github_installations (
  user_id uuid not null references auth.users on delete cascade,
  installation_id bigint not null,
  github_account_login text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, installation_id)
);
-- One installation can belong to only one app user
create unique index if not exists github_installations_installation_idx
  on public.github_installations (installation_id);
alter table public.github_installations enable row level security;

drop policy if exists "read own installations" on public.github_installations;
create policy "read own installations" on public.github_installations
  for select using ((select auth.uid()) = user_id);

-- Single-use, short-lived `state` values for the install flow. Only the SHA-256 hash is stored.
-- RLS on with no policies: backend-only.
create table if not exists public.github_install_states (
  state_hash text primary key,
  user_id uuid not null references auth.users on delete cascade,
  expires_at timestamptz not null
);
alter table public.github_install_states enable row level security;
create index if not exists github_install_states_user_idx on public.github_install_states (user_id);

-- Every write the app makes to GitHub on a user's behalf
create table if not exists public.github_audit_log (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users on delete cascade,
  installation_id bigint not null,
  repo text not null,
  action text not null,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
alter table public.github_audit_log enable row level security;
create index if not exists github_audit_log_user_idx on public.github_audit_log (user_id, created_at desc);

drop policy if exists "read own audit log" on public.github_audit_log;
create policy "read own audit log" on public.github_audit_log
  for select using ((select auth.uid()) = user_id);
