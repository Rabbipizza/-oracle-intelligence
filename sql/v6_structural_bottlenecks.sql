create table if not exists public.oracle_v6_structural_bottlenecks (
  id bigserial primary key,
  experiment_id bigint references public.oracle_v6_experiments(id) on delete cascade,
  trend_node text not null,
  bottleneck_node text not null,
  category text not null check (category in ('RAW_MATERIAL','ENERGY','INFRASTRUCTURE','COMPONENT','TECHNOLOGY','CAPACITY','PROCESS')),
  dependency_type text not null check (dependency_type in ('PHYSICAL_INPUT','TECHNICAL_PREREQUISITE','CAPACITY_PREREQUISITE','INFRASTRUCTURE_PREREQUISITE')),
  structural_status text not null default 'STRUCTURAL_CANDIDATE' check (structural_status in ('STRUCTURAL_CANDIDATE','EVIDENCE_BACKED','VALIDATED_PREDICTIVE')),
  necessity_reason text not null,
  derivation_rule text not null,
  signal_available_at timestamptz not null,
  evaluation_as_of timestamptz not null,
  independent_source_count integer not null default 0,
  evidence_ids jsonb not null default '[]'::jsonb,
  forecast_probability double precision,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(experiment_id,trend_node,bottleneck_node,evaluation_as_of)
);
create index if not exists oracle_v6_structural_bottlenecks_eval_idx on public.oracle_v6_structural_bottlenecks(evaluation_as_of,trend_node);
alter table public.oracle_v6_structural_bottlenecks enable row level security;
revoke all on public.oracle_v6_structural_bottlenecks from anon, authenticated;
comment on table public.oracle_v6_structural_bottlenecks is 'PIT structural dependency candidates. STRUCTURAL_CANDIDATE is not a causal or probabilistic forecast.';
