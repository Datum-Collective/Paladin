-- Remediations that change code. Run after 0004. Safe to re-run.
-- kind 'model' is the original analysed-environment fix; kind 'code' carries a unified diff for real files.
alter table public.remediations add column if not exists kind text not null default 'model' check (kind in ('model', 'code'));
alter table public.remediations add column if not exists job bigint references public.jobs on delete set null;
alter table public.remediations add column if not exists patch text not null default '' check (octet_length(patch) <= 400000);
alter table public.remediations add column if not exists files jsonb not null default '[]'::jsonb check (pg_column_size(files) <= 100000);
alter table public.remediations add column if not exists applied text not null default '' check (char_length(applied) <= 500);
alter table public.remediations add column if not exists finding_ids jsonb not null default '[]'::jsonb check (pg_column_size(finding_ids) <= 20000);
