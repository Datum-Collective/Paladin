-- GitHub-only auth: profiles + per-source ingest API keys.
-- Run in the Supabase SQL editor (or `supabase db push`).

-- Profile row auto-created on first GitHub login
create table if not exists public.profiles (
  id uuid primary key references auth.users on delete cascade,
  github_username text,
  avatar_url text,
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;

drop policy if exists "read own profile" on public.profiles;
create policy "read own profile" on public.profiles
  for select using ((select auth.uid()) = id);

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  insert into public.profiles (id, github_username, avatar_url)
  values (new.id,
          new.raw_user_meta_data->>'user_name',
          new.raw_user_meta_data->>'avatar_url')
  on conflict (id) do nothing;
  return new;
end; $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Per-source ingest keys. Only the SHA-256 hash is stored.
-- RLS on with no policies: only the backend (service key) can touch this table.
create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  source text not null check (source in ('linux_auth', 'suricata', 'web_access')),
  key_prefix text not null,
  key_hash text not null unique,
  created_at timestamptz not null default now(),
  revoked_at timestamptz
);
alter table public.api_keys enable row level security;
create index if not exists api_keys_user_idx on public.api_keys (user_id);
