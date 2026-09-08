-- ORACLE V6 scientific schema
-- Non-destructive: additive tables only. Existing V5 tables/workers are preserved.

create table if not exists public.oracle_v6_experiments (
  id bigserial primary key,
  experiment_key text not null unique,
  created_at timestamptz not null default now(),
  model_family text not null,
  model_version text,
  target_name text not null,
  horizon_months int,
  train_start date,
  train_end date,
  validation_start date,
  validation_end date,
  test_start date,
  test_end date,
  holdout boolean not null default false,
  specification jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  invalidated_at timestamptz,
  invalidation_reason text
);

create table if not exists public.oracle_v6_pit_observations (
  id bigserial primary key,
  source_type text not null,
  source_id text not null,
  entity_key text,
  event_date timestamptz,
  published_at timestamptz,
  available_at timestamptz not null,
  ingested_at timestamptz not null default now(),
  vintage_id text,
  payload_hash text,
  metadata jsonb not null default '{}'::jsonb,
  unique(source_type, source_id, available_at, coalesce(vintage_id,''))
);

create index if not exists idx_oracle_v6_pit_available_at
  on public.oracle_v6_pit_observations(available_at);
create index if not exists idx_oracle_v6_pit_entity
  on public.oracle_v6_pit_observations(entity_key, available_at);

create table if not exists public.oracle_v6_signal_null_models (
  id bigserial primary key,
  signal_key text not null,
  as_of timestamptz not null,
  null_family text not null,
  observed_value double precision,
  expected_value double precision,
  dispersion double precision,
  surprise_z double precision,
  p_value double precision,
  model_version text,
  training_window jsonb,
  diagnostics jsonb not null default '{}'::jsonb,
  unique(signal_key, as_of, null_family, coalesce(model_version,''))
);

create table if not exists public.oracle_v6_trend_probabilities (
  id bigserial primary key,
  trend_key text not null,
  as_of timestamptz not null,
  first_detected_at timestamptz not null,
  state text not null check (state in ('NOISE','SIGNAL','EMERGING','ACCELERATING','CONFIRMED','MATURE','DECLINING')),
  p_structural double precision not null check (p_structural between 0 and 1),
  novelty double precision,
  acceleration double precision,
  persistence double precision,
  source_diversity double precision,
  convergence double precision,
  model_version text,
  evidence_ids jsonb not null default '[]'::jsonb,
  unique(trend_key, as_of, coalesce(model_version,''))
);

create table if not exists public.oracle_v6_graph_edges (
  id bigserial primary key,
  source_node text not null,
  target_node text not null,
  valid_from timestamptz not null,
  valid_to timestamptz,
  sign smallint check (sign in (-1,1)),
  mechanism text,
  expected_lag_days int,
  elasticity_low double precision,
  elasticity_high double precision,
  status text not null check (status in ('HYPOTHESIS','SUPPORTED_DESCRIPTIVE','SUPPORTED_PREDICTIVE','SUPPORTED_CAUSAL','REJECTED')),
  posterior_probability double precision check (posterior_probability between 0 and 1),
  independent_source_count int not null default 0,
  evidence_ids jsonb not null default '[]'::jsonb,
  validation_method text,
  validation_stats jsonb not null default '{}'::jsonb,
  generated_by_model text,
  prompt_hash text,
  evidence_cutoff_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists public.oracle_v6_bottleneck_forecasts (
  id bigserial primary key,
  bottleneck_key text not null,
  as_of timestamptz not null,
  horizon_months int not null check (horizon_months in (6,12,24,36)),
  probability double precision not null check (probability between 0 and 1),
  ci_low double precision,
  ci_high double precision,
  demand_forecast jsonb,
  effective_supply_forecast jsonb,
  covariates jsonb not null default '{}'::jsonb,
  model_version text,
  realized_outcome boolean,
  realized_at timestamptz,
  brier_component double precision,
  unique(bottleneck_key, as_of, horizon_months, coalesce(model_version,''))
);

create table if not exists public.oracle_v6_company_capture (
  id bigserial primary key,
  ticker text not null,
  trend_key text not null,
  as_of timestamptz not null,
  revenue_exposure double precision,
  expected_incremental_revenue jsonb,
  expected_incremental_margin jsonb,
  pricing_power_probability double precision,
  deliverable_capacity_probability double precision,
  expected_incremental_fcf jsonb,
  capex_required jsonb,
  capture_probability double precision check (capture_probability between 0 and 1),
  model_version text,
  evidence_ids jsonb not null default '[]'::jsonb,
  unique(ticker, trend_key, as_of, coalesce(model_version,''))
);

create table if not exists public.oracle_v6_market_expectations (
  id bigserial primary key,
  ticker text not null,
  as_of timestamptz not null,
  reverse_dcf_assumptions jsonb not null default '{}'::jsonb,
  implied_fundamentals jsonb not null default '{}'::jsonb,
  fundamental_forecast jsonb not null default '{}'::jsonb,
  p_fundamentals_exceed_expectations double precision check (p_fundamentals_exceed_expectations between 0 and 1),
  gap_magnitude jsonb,
  model_version text,
  unique(ticker, as_of, coalesce(model_version,''))
);

create table if not exists public.oracle_v6_return_targets (
  id bigserial primary key,
  ticker text not null,
  as_of date not null,
  horizon_months int not null check (horizon_months in (3,6,12,24)),
  realized_return double precision,
  expected_factor_return double precision,
  residual_return double precision,
  transaction_cost double precision default 0,
  residual_return_net double precision,
  factor_model_version text,
  unique(ticker, as_of, horizon_months, coalesce(factor_model_version,''))
);

create table if not exists public.oracle_v6_model_predictions (
  id bigserial primary key,
  experiment_id bigint references public.oracle_v6_experiments(id) on delete cascade,
  ticker text,
  trend_key text,
  as_of timestamptz not null,
  target_name text not null,
  horizon_months int,
  prediction double precision,
  probability double precision,
  lower_bound double precision,
  upper_bound double precision,
  realized_value double precision,
  baseline_prediction double precision,
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.oracle_v6_multiple_testing (
  id bigserial primary key,
  experiment_id bigint references public.oracle_v6_experiments(id) on delete cascade,
  hypothesis_key text not null,
  raw_p_value double precision,
  adjusted_p_value double precision,
  method text,
  selected boolean,
  created_at timestamptz not null default now()
);

create table if not exists public.oracle_v6_decisions (
  id bigserial primary key,
  ticker text not null,
  as_of timestamptz not null,
  decision text not null check (decision in ('BUY_CANDIDATE','PILOT_BUY','WATCH','WAIT','NO_EDGE','NO_ACTION','REJECT')),
  p_structural double precision,
  p_bottleneck double precision,
  p_economic_capture double precision,
  p_fundamentals_exceed_expectations double precision,
  expected_residual_return double precision,
  uncertainty jsonb,
  invalidation_conditions jsonb not null default '[]'::jsonb,
  data_gaps jsonb not null default '[]'::jsonb,
  model_version text,
  unique(ticker, as_of, coalesce(model_version,''))
);

-- RLS is enabled proactively because public is normally Data-API exposed in Supabase.
alter table public.oracle_v6_experiments enable row level security;
alter table public.oracle_v6_pit_observations enable row level security;
alter table public.oracle_v6_signal_null_models enable row level security;
alter table public.oracle_v6_trend_probabilities enable row level security;
alter table public.oracle_v6_graph_edges enable row level security;
alter table public.oracle_v6_bottleneck_forecasts enable row level security;
alter table public.oracle_v6_company_capture enable row level security;
alter table public.oracle_v6_market_expectations enable row level security;
alter table public.oracle_v6_return_targets enable row level security;
alter table public.oracle_v6_model_predictions enable row level security;
alter table public.oracle_v6_multiple_testing enable row level security;
alter table public.oracle_v6_decisions enable row level security;

-- No public policies are created here. Service-side workers should use protected credentials.
-- Add narrowly scoped authenticated policies only after the access model is defined.
