create table if not exists public.oracle_v6_evaluation_runs (
  id bigserial primary key,
  experiment_id bigint not null references public.oracle_v6_experiments(id),
  external_run_id text not null,
  signal_available_at timestamptz not null,
  evaluation_as_of timestamptz not null,
  created_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);
create unique index if not exists oracle_v6_evaluation_runs_external_uq
  on public.oracle_v6_evaluation_runs(external_run_id);
create index if not exists oracle_v6_evaluation_runs_exp_idx
  on public.oracle_v6_evaluation_runs(experiment_id,evaluation_as_of desc);
alter table public.oracle_v6_evaluation_runs enable row level security;
