-- P0-7 schema mirror for Supabase migrations p0_7_sequential_multiple_testing
-- and p0_7_candidate_replication_threshold.
create table if not exists public.oracle_v6_sequential_fdr_config (
  config_version text primary key,target_alpha double precision not null,
  gamma_rule text not null,min_replication_days integer not null,
  min_new_document_ratio double precision not null,min_new_documents integer not null,
  min_qualifying_replications integer not null,candidate_replications integer not null default 3,
  active boolean not null default true,created_at timestamptz not null default now()
);
create table if not exists public.oracle_v6_sequential_run_budget (
  id bigint generated always as identity primary key,
  config_version text not null references public.oracle_v6_sequential_fdr_config(config_version),
  experiment_id bigint not null references public.oracle_v6_experiments(id),
  test_week date not null,decision_as_of timestamptz not null,family_fingerprint text not null unique,
  sequence_index integer not null unique,gamma_weight double precision not null,
  allocated_alpha double precision not null,cumulative_allocated_alpha double precision not null check(cumulative_allocated_alpha<=0.0500000001),
  family_size integer not null,document_count integer not null default 0,created_at timestamptz not null default now()
);
create table if not exists public.oracle_v6_signal_lifecycle (
  id bigint generated always as identity primary key,experiment_id bigint not null references public.oracle_v6_experiments(id),
  trend_key text not null,lifecycle_state text not null check(lifecycle_state in ('EPHEMERAL_SIGNAL','REPLICATED_SIGNAL','CANDIDATE_FOR_SEMANTIC_BRIDGE')),
  first_seen_at timestamptz not null,last_seen_at timestamptz not null,qualifying_replications integer not null default 0,
  replication_dates jsonb not null default '[]'::jsonb,alpha_trace jsonb not null default '[]'::jsonb,
  last_family_fingerprint text,last_adjusted_p_value double precision,last_raw_p_value double precision,updated_at timestamptz not null default now(),
  unique(experiment_id,trend_key)
);
create table if not exists public.oracle_v6_signal_lifecycle_observations (
  id bigint generated always as identity primary key,lifecycle_id bigint not null references public.oracle_v6_signal_lifecycle(id) on delete cascade,
  family_fingerprint text not null references public.oracle_v6_sequential_run_budget(family_fingerprint),test_week date not null,
  decision_as_of timestamptz not null,bh_selected boolean not null,raw_p_value double precision,adjusted_p_value double precision,
  allocated_alpha double precision not null,document_count integer not null default 0,new_document_count integer not null default 0,
  new_document_ratio double precision,days_since_last_qualifying integer,qualifies_as_independent_replication boolean not null default false,
  created_at timestamptz not null default now(),unique(lifecycle_id,family_fingerprint)
);