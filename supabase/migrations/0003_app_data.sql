-- All application data in Supabase: workspaces, events, analysis state, scans, remediations, preferences.
-- Run in the Supabase SQL editor after 0001_auth.sql and 0002_github.sql. Safe to re-run.
--
-- The backend talks to Supabase AS THE SIGNED-IN USER (their access token + the public anon key), on the
-- web server and in the desktop app alike. Row-level security below is therefore the primary access control:
-- a user can read and write only rows whose user_id is their own, and only inside workspaces they own.
-- Anyone can call this API directly with their own token, so every limit that matters is enforced here
-- (row caps, value sizes, generated ids), not only in the backend.

-- ---------- helpers ----------
create or replace function public.owns_workspace(p_ws bigint) returns boolean
language sql stable security invoker set search_path = '' as $$
  select exists (select 1 from public.workspaces w where w.id = p_ws and w.user_id = (select auth.uid()));
$$;

-- ---------- workspaces ----------
create table if not exists public.workspaces (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  name text not null check (char_length(name) between 1 and 60),
  repo_url text check (repo_url is null or char_length(repo_url) <= 1000),
  created double precision not null default extract(epoch from now()),
  opened double precision not null default extract(epoch from now())
);
create unique index if not exists workspaces_user_name_idx on public.workspaces (user_id, lower(name));
create index if not exists workspaces_user_opened_idx on public.workspaces (user_id, opened desc);
alter table public.workspaces enable row level security;

drop policy if exists "own workspaces" on public.workspaces;
create policy "own workspaces" on public.workspaces for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

create or replace function public.cap_workspaces() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if (select count(*) from public.workspaces where user_id = new.user_id) >= 50 then
    raise exception 'workspace limit reached' using errcode = 'check_violation';
  end if;
  return new;
end $$;
drop trigger if exists cap_workspaces on public.workspaces;
create trigger cap_workspaces before insert on public.workspaces for each row execute function public.cap_workspaces();

-- The workspace each user last opened
create table if not exists public.active_ws (
  user_id uuid primary key default auth.uid() references auth.users on delete cascade,
  ws bigint not null references public.workspaces on delete cascade
);
alter table public.active_ws enable row level security;
drop policy if exists "own active workspace" on public.active_ws;
create policy "own active workspace" on public.active_ws for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()) and public.owns_workspace(ws));

-- ---------- per-user preferences ----------
create table if not exists public.prefs (
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  key text not null check (key ~ '^[a-z_]{1,32}\.[a-z_]{1,32}$'),
  value jsonb not null check (pg_column_size(value) <= 1024),
  primary key (user_id, key)
);
alter table public.prefs enable row level security;
drop policy if exists "own prefs" on public.prefs;
create policy "own prefs" on public.prefs for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

create or replace function public.cap_prefs() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if (select count(*) from public.prefs where user_id = new.user_id) >= 100 then
    raise exception 'too many preferences' using errcode = 'check_violation';
  end if;
  return new;
end $$;
drop trigger if exists cap_prefs on public.prefs;
create trigger cap_prefs before insert on public.prefs for each row execute function public.cap_prefs();

-- ---------- workspace-scoped data ----------
-- Every table below carries user_id (RLS) and ws (must be a workspace the same user owns).

create table if not exists public.events (
  seq bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  data jsonb not null check (pg_column_size(data) <= 16384)
);
create index if not exists events_ws_seq_idx on public.events (ws, seq);

create table if not exists public.fixes (
  ws bigint not null references public.workspaces on delete cascade,
  edge text not null check (char_length(edge) <= 200),
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  primary key (ws, edge)
);

create table if not exists public.sim (
  ws bigint primary key references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  pos integer not null check (pos >= 0)
);

create table if not exists public.remediations (
  id bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  edges jsonb not null check (pg_column_size(edges) <= 16384),
  state text not null check (state in ('proposed', 'approved', 'executed', 'verified', 'failed', 'rolled_back')),
  title text not null check (char_length(title) <= 120),
  runbook text not null check (char_length(runbook) <= 20000),
  ai_drafted boolean not null default false,
  connector text not null check (char_length(connector) <= 32),
  mark integer not null default 0,
  note text not null default '' check (char_length(note) <= 2000),
  risk_before double precision,
  risk_after double precision,
  paths_before integer,
  paths_after integer,
  created double precision not null,
  updated double precision not null
);
create index if not exists remediations_ws_idx on public.remediations (ws, id desc);

create table if not exists public.audit (
  id bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  rem bigint not null,
  actor text not null check (char_length(actor) <= 320),
  action text not null check (char_length(action) <= 32),
  detail text not null default '' check (char_length(detail) <= 500),
  ts double precision not null
);
create index if not exists audit_ws_idx on public.audit (ws, id desc);

create table if not exists public.jobs (
  id bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  repo_url text not null check (char_length(repo_url) <= 1000),
  state text not null check (char_length(state) <= 16),
  log jsonb not null default '[]'::jsonb check (pg_column_size(log) <= 200000),
  findings jsonb not null default '[]'::jsonb check (pg_column_size(findings) <= 2000000),
  fixes jsonb not null default '[]'::jsonb check (pg_column_size(fixes) <= 200000),
  report jsonb not null default '{}'::jsonb check (pg_column_size(report) <= 500000),
  branch text not null default '' check (char_length(branch) <= 200),
  pr_url text not null default '' check (char_length(pr_url) <= 300),
  diff text not null default '' check (octet_length(diff) <= 1000000),
  ai_used boolean not null default false,
  error text not null default '' check (char_length(error) <= 500),
  created double precision not null,
  updated double precision not null
);
create index if not exists jobs_ws_idx on public.jobs (ws, id desc);

create table if not exists public.code_models (
  ws bigint primary key references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  repo text not null check (char_length(repo) <= 1000),
  created double precision not null,
  ai_used boolean not null default false,
  files integer not null default 0,
  model jsonb not null check (pg_column_size(model) <= 2000000),
  findings jsonb not null check (pg_column_size(findings) <= 2000000)
);

-- Same policy on every workspace-scoped table
do $$
declare t text;
begin
  foreach t in array array['events', 'fixes', 'sim', 'remediations', 'audit', 'jobs', 'code_models'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists "own rows in own workspaces" on public.%I', t);
    execute format('create policy "own rows in own workspaces" on public.%I for all to authenticated '
                   'using (user_id = (select auth.uid())) '
                   'with check (user_id = (select auth.uid()) and public.owns_workspace(ws))', t);
  end loop;
end $$;

-- Row caps per workspace (bulk-safe for events: checked once per statement)
create or replace function public.cap_events() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  if exists (select 1 from public.events e where e.ws in (select distinct n.ws from new_rows n)
             group by e.ws having count(*) > 50000) then
    raise exception 'event limit reached for this workspace' using errcode = 'check_violation';
  end if;
  return null;
end $$;
drop trigger if exists cap_events on public.events;
create trigger cap_events after insert on public.events referencing new table as new_rows
  for each statement execute function public.cap_events();

create or replace function public.cap_per_workspace() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare n bigint;
begin
  execute format('select count(*) from public.%I where ws = $1', tg_table_name) into n using new.ws;
  if n >= tg_argv[0]::bigint then
    raise exception '% limit reached for this workspace', tg_table_name using errcode = 'check_violation';
  end if;
  return new;
end $$;
drop trigger if exists cap_fixes on public.fixes;
create trigger cap_fixes before insert on public.fixes for each row execute function public.cap_per_workspace('5000');
drop trigger if exists cap_remediations on public.remediations;
create trigger cap_remediations before insert on public.remediations for each row execute function public.cap_per_workspace('1000');
drop trigger if exists cap_audit on public.audit;
create trigger cap_audit before insert on public.audit for each row execute function public.cap_per_workspace('20000');
drop trigger if exists cap_jobs on public.jobs;
create trigger cap_jobs before insert on public.jobs for each row execute function public.cap_per_workspace('500');

-- One round trip for the workspace list: event counts and newest scan per workspace (RLS still applies)
create or replace function public.workspace_event_counts(p_ws bigint[])
returns table (ws bigint, n bigint)
language sql stable security invoker set search_path = '' as $$
  select e.ws, count(*) from public.events e where e.ws = any(p_ws) group by e.ws;
$$;

create or replace function public.workspace_latest_jobs(p_ws bigint[])
returns table (ws bigint, id bigint, state text, error text, updated double precision)
language sql stable security invoker set search_path = '' as $$
  select distinct on (j.ws) j.ws, j.id, j.state, j.error, j.updated
  from public.jobs j where j.ws = any(p_ws) order by j.ws, j.id desc;
$$;

-- ---------- ingest API keys (table from 0001) ----------
alter table public.api_keys add column if not exists label text not null default 'source'
  check (char_length(label) <= 64);
alter table public.api_keys add column if not exists ws bigint references public.workspaces on delete cascade;
alter table public.api_keys alter column source drop not null;
alter table public.api_keys drop constraint if exists api_keys_source_check;

-- Users manage their own keys, but can never read a key's hash back, and can only revoke (not edit) a key
revoke all on public.api_keys from anon, authenticated;
grant select (id, user_id, source, label, key_prefix, ws, created_at, revoked_at) on public.api_keys to authenticated;
grant insert (user_id, source, label, key_prefix, key_hash, ws) on public.api_keys to authenticated;
grant update (revoked_at) on public.api_keys to authenticated;

drop policy if exists "read own keys" on public.api_keys;
create policy "read own keys" on public.api_keys for select to authenticated
  using (user_id = (select auth.uid()));
drop policy if exists "create own keys" on public.api_keys;
create policy "create own keys" on public.api_keys for insert to authenticated
  with check (user_id = (select auth.uid()) and (ws is null or public.owns_workspace(ws)));
drop policy if exists "revoke own keys" on public.api_keys;
create policy "revoke own keys" on public.api_keys for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- Log shippers have an API key, not a session. This checks the key and writes only into that key's workspace
-- (or the owner's oldest one for keys made before workspaces). Runs as its owner so it can read api_keys.
create or replace function public.ingest_with_key(p_key text, p_events jsonb)
returns json language plpgsql security definer set search_path = '' as $$
declare
  k record;
  target bigint;
  room bigint;
  n bigint;
begin
  if p_key is null or left(p_key, 4) <> 'apc_' or char_length(p_key) > 200
     or jsonb_typeof(p_events) <> 'array' or jsonb_array_length(p_events) > 2000 then
    raise exception 'invalid request' using errcode = 'invalid_parameter_value';
  end if;
  select a.user_id, a.ws into k from public.api_keys a
   where a.key_hash = encode(extensions.digest(p_key, 'sha256'), 'hex') and a.revoked_at is null;
  if not found then
    raise exception 'invalid api key' using errcode = 'invalid_authorization_specification';
  end if;
  target := k.ws;
  if target is null or not exists (select 1 from public.workspaces w where w.id = target and w.user_id = k.user_id) then
    select w.id into target from public.workspaces w where w.user_id = k.user_id order by w.created, w.id limit 1;
  end if;
  if target is null then
    raise exception 'no workspace for this key' using errcode = 'invalid_parameter_value';
  end if;
  room := greatest(0, 50000 - (select count(*) from public.events e where e.ws = target));
  insert into public.events (ws, user_id, data)
    select target, k.user_id, x.e from jsonb_array_elements(p_events) with ordinality as x(e, i)
    where x.i <= room and pg_column_size(x.e) <= 16384;
  get diagnostics n = row_count;
  return json_build_object('accepted', n, 'ws', target);
end $$;
revoke all on function public.ingest_with_key(text, jsonb) from public;
grant execute on function public.ingest_with_key(text, jsonb) to anon, authenticated;

-- ---------- GitHub audit log (table from 0002) ----------
-- Append-only. Web writes go through the GitHub App with the service key (via = 'app'); the desktop app,
-- which has no service key, records writes made with the user's own token (via = 'token').
alter table public.github_audit_log alter column installation_id drop not null;
alter table public.github_audit_log add column if not exists via text not null default 'app'
  check (via in ('app', 'token'));
drop policy if exists "desktop appends own audit rows" on public.github_audit_log;
create policy "desktop appends own audit rows" on public.github_audit_log for insert to authenticated
  with check (user_id = (select auth.uid()) and via = 'token' and installation_id is null);
