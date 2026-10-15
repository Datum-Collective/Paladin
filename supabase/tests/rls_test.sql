-- Row-level security check for 0003_app_data.sql. Paste into the Supabase SQL editor and run.
-- It creates two throwaway users, acts as each of them, tries to reach the other's data, and ROLLS EVERYTHING BACK.
-- Success: the output ends with "RLS checks passed". Any failure stops with a message saying what leaked.
begin;

insert into auth.users (id, instance_id, aud, role, email)
values ('00000000-0000-4000-a000-00000000000a', '00000000-0000-0000-0000-000000000000', 'authenticated',
        'authenticated', 'rls-test-a@example.invalid'),
       ('00000000-0000-4000-a000-00000000000b', '00000000-0000-0000-0000-000000000000', 'authenticated',
        'authenticated', 'rls-test-b@example.invalid');

do $$
declare
  a uuid := '00000000-0000-4000-a000-00000000000a';
  b uuid := '00000000-0000-4000-a000-00000000000b';
  ws_a bigint;
  ws_b bigint;
  n bigint;
begin
  execute 'set local role authenticated';

  -- ---- user A creates data ----
  perform set_config('request.jwt.claims', json_build_object('sub', a, 'role', 'authenticated')::text, true);
  insert into public.workspaces (name) values ('rls test A') returning id into ws_a;
  insert into public.events (ws, data) values (ws_a, '{"ts":"2024-01-01T00:00:00Z","source":"t","type":"t"}');
  insert into public.jobs (ws, repo_url, state, created, updated) values (ws_a, 'a/b', 'done', 0, 0);
  insert into public.remediations (ws, edges, state, title, runbook, connector, created, updated)
    values (ws_a, '["e1"]', 'proposed', 't', 'r', 'model', 0, 0);
  insert into public.prefs (key, value) values ('diff.wrap', 'true');
  insert into public.api_keys (user_id, label, key_prefix, key_hash, ws) values (a, 'k', 'apc_aaaaaa', 'hash-a', ws_a);
  select count(*) into n from public.workspaces where id = ws_a;
  assert n = 1, 'A cannot read its own workspace';

  -- ---- user B tries to reach it ----
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  insert into public.workspaces (name) values ('rls test B') returning id into ws_b;
  select count(*) into n from public.workspaces where id = ws_a;       assert n = 0, 'B can read A''s workspace';
  select count(*) into n from public.events where ws = ws_a;           assert n = 0, 'B can read A''s events';
  select count(*) into n from public.jobs where ws = ws_a;             assert n = 0, 'B can read A''s scans';
  select count(*) into n from public.remediations where ws = ws_a;     assert n = 0, 'B can read A''s remediations';
  select count(*) into n from public.prefs where user_id = a;          assert n = 0, 'B can read A''s preferences';
  select count(*) into n from public.api_keys where user_id = a;       assert n = 0, 'B can read A''s API keys';
  select count(*) into n from public.active_ws where user_id = a;      assert n = 0, 'B can read A''s active workspace';

  update public.workspaces set name = 'pwned' where id = ws_a;
  get diagnostics n = row_count;                                        assert n = 0, 'B can rename A''s workspace';
  delete from public.events where ws = ws_a;
  get diagnostics n = row_count;                                        assert n = 0, 'B can delete A''s events';
  update public.api_keys set revoked_at = now() where user_id = a;
  get diagnostics n = row_count;                                        assert n = 0, 'B can revoke A''s key';

  begin
    insert into public.events (ws, data) values (ws_a, '{}');
    raise exception 'B wrote an event into A''s workspace';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.events (ws, user_id, data) values (ws_b, a, '{}');
    raise exception 'B wrote a row owned by A';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.active_ws (ws) values (ws_a);
    raise exception 'B pointed its active workspace at A''s';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.api_keys (user_id, label, key_prefix, key_hash, ws) values (b, 'k', 'apc_bbbbbb', 'hash-b', ws_a);
    raise exception 'B bound an API key to A''s workspace';
  exception when insufficient_privilege then null;
  end;
  begin
    perform key_hash from public.api_keys limit 1;
    raise exception 'API key hashes are readable';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.workspaces (id, name) values (999999999, 'chosen id');
    raise exception 'a generated id can be chosen';
  exception when generated_always then null;
  end;

  -- ---- GitHub App tables: service key only (desktop may append its own token-made audit rows) ----
  begin
    insert into public.github_installations (user_id, installation_id, github_account_login) values (b, 1, 'x');
    raise exception 'a user can link a GitHub installation directly';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.github_install_states (state_hash, user_id, expires_at) values ('h', b, now() + interval '1 hour');
    raise exception 'a user can create install states';
  exception when insufficient_privilege then null;
  end;
  begin
    insert into public.github_audit_log (user_id, installation_id, repo, action, via) values (b, 5, 'x/y', 'commit', 'app');
    raise exception 'a user can forge GitHub App audit rows';
  exception when insufficient_privilege then null;
  end;
  insert into public.github_audit_log (user_id, repo, action, via) values (b, 'x/y', 'commit', 'token');

  -- ---- anonymous role sees nothing ----
  execute 'set local role anon';
  perform set_config('request.jwt.claims', '{"role":"anon"}', true);
  select count(*) into n from public.workspaces;                        assert n = 0, 'anon can read workspaces';
  select count(*) into n from public.events;                            assert n = 0, 'anon can read events';

  raise notice 'RLS checks passed';
end $$;

rollback;
