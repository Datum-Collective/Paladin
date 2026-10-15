-- Assistant conversations, kept per workspace. Run after 0003_app_data.sql. Safe to re-run.
--
-- A conversation belongs to one workspace; its messages belong to that conversation AND carry the same workspace,
-- so row-level security can scope both tables the same way as every other workspace table, and a message can never
-- be filed under someone else's (or another workspace's) conversation. Provider keys are never stored here.

create table if not exists public.conversations (
  id bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  title text not null check (char_length(title) between 1 and 120),
  created double precision not null,
  updated double precision not null
);

create table if not exists public.messages (
  id bigint generated always as identity primary key,
  ws bigint not null references public.workspaces on delete cascade,
  conversation bigint not null references public.conversations on delete cascade,
  user_id uuid not null default auth.uid() references auth.users on delete cascade,
  -- the browser's id for a submitted message: a retried or double-clicked send is recognised, not stored twice
  client_id text check (client_id is null or char_length(client_id) <= 64),
  role text not null check (role in ('user', 'assistant')),
  content text not null default '' check (char_length(content) <= 40000),
  -- streaming: being written; interrupted: the app closed mid-answer (set by the reader); stopped: by the user
  status text not null default 'complete' check (status in ('complete', 'streaming', 'stopped', 'error', 'interrupted')),
  meta jsonb not null default '{}'::jsonb check (pg_column_size(meta) <= 20000),
  created double precision not null,
  updated double precision not null,
  unique (conversation, client_id)
);

create index if not exists conversations_ws_updated on public.conversations (ws, updated desc);
create index if not exists messages_conversation_id on public.messages (conversation, id);

-- Same rule as every workspace table, plus: a message's conversation must be in the message's own workspace
alter table public.conversations enable row level security;
drop policy if exists "own rows in own workspaces" on public.conversations;
create policy "own rows in own workspaces" on public.conversations for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()) and public.owns_workspace(ws));

create or replace function public.conversation_in_workspace(p_conv bigint, p_ws bigint) returns boolean
language sql stable security invoker set search_path = '' as $$
  select exists (select 1 from public.conversations c
                  where c.id = p_conv and c.ws = p_ws and c.user_id = (select auth.uid()));
$$;

alter table public.messages enable row level security;
drop policy if exists "own rows in own conversations" on public.messages;
create policy "own rows in own conversations" on public.messages for all to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()) and public.owns_workspace(ws)
              and public.conversation_in_workspace(conversation, ws));

-- Row caps (the API is reachable directly with a user's token, so the limits live here)
drop trigger if exists cap_conversations on public.conversations;
create trigger cap_conversations before insert on public.conversations
  for each row execute function public.cap_per_workspace('500');

create or replace function public.cap_messages() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare n bigint;
begin
  select count(*) into n from public.messages where conversation = new.conversation;
  if n >= 2000 then
    raise exception 'message limit reached for this conversation' using errcode = 'check_violation';
  end if;
  return new;
end $$;
drop trigger if exists cap_messages on public.messages;
create trigger cap_messages before insert on public.messages for each row execute function public.cap_messages();
