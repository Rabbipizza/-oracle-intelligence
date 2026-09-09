create table if not exists public.oracle_v6_structural_company_exposure (
  id bigserial primary key,
  experiment_id bigint not null references public.oracle_v6_experiments(id) on delete cascade,
  evaluation_as_of timestamptz not null,
  trend_node text not null,
  bottleneck_node text not null,
  ticker text not null,
  exposure_status text not null default 'STRUCTURAL_EXPOSURE_CANDIDATE',
  evidence_key text not null,
  evidence_id bigint not null,
  evidence_available_at timestamptz not null,
  source_url text,
  excerpt text,
  mapping_rule text not null,
  created_at timestamptz not null default now(),
  constraint oracle_v6_structural_company_exposure_status_chk check (exposure_status in ('STRUCTURAL_EXPOSURE_CANDIDATE','EVIDENCE_BACKED_EXPOSURE')),
  constraint oracle_v6_structural_company_exposure_pit_chk check (evidence_available_at <= evaluation_as_of),
  unique (experiment_id,evaluation_as_of,bottleneck_node,ticker,evidence_id,mapping_rule)
);
create index if not exists oracle_v6_structural_company_exposure_lookup_idx
  on public.oracle_v6_structural_company_exposure(experiment_id,evaluation_as_of,bottleneck_node,ticker);
alter table public.oracle_v6_structural_company_exposure enable row level security;
revoke all on public.oracle_v6_structural_company_exposure from anon, authenticated;
comment on table public.oracle_v6_structural_company_exposure is
'PIT evidence bridge from structural bottleneck candidates to listed-company exposure. No return, capture, scarcity or investment probability is implied.';
