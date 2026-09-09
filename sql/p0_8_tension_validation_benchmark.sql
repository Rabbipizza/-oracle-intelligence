-- P0-8 schema mirror. Production migration names:
-- p0_8_tension_validation_benchmark / p0_8_tension_annotation_adjudication.
-- Thresholds are pre-registered: precision(REAL_TENSION)>=0.90, Cohen kappa>=0.60,
-- double-annotated sample size>=200.

create table if not exists public.oracle_v6_tension_validation_config (
  config_version text primary key,
  required_real_tension_precision double precision not null,
  minimum_kappa double precision not null,
  minimum_sample_size integer not null,
  labels jsonb not null,active boolean not null default true,created_at timestamptz not null default now()
);
create table if not exists public.oracle_v6_tension_annotation_sample (
  id bigint generated always as identity primary key,
  evidence_id bigint not null references public.oracle_v4_sec_economic_evidence(id),
  bottleneck_node text,stratum text not null,ticker text,evidence_key text,excerpt text not null,
  current_classifier_positive boolean not null,sample_version text not null default 'TENSION_SAMPLE_V1',
  sampled_at timestamptz not null default now()
);
create table if not exists public.oracle_v6_tension_annotations (
  id bigint generated always as identity primary key,sample_id bigint not null references public.oracle_v6_tension_annotation_sample(id) on delete cascade,
  annotator_id text not null,label text not null,notes text,annotated_at timestamptz not null default now(),unique(sample_id,annotator_id)
);
create table if not exists public.oracle_v6_tension_adjudications (
  id bigint generated always as identity primary key,sample_id bigint not null unique references public.oracle_v6_tension_annotation_sample(id) on delete cascade,
  adjudicator_id text not null,label text not null,reason text not null,adjudicated_at timestamptz not null default now()
);
create table if not exists public.oracle_v6_tension_benchmark_runs (
  id bigint generated always as identity primary key,benchmark_version text not null,sample_version text not null,
  sample_size integer not null,double_annotated_size integer not null,cohen_kappa double precision,per_class_metrics jsonb not null default '{}'::jsonb,
  real_tension_precision double precision,real_tension_recall double precision,real_tension_f1 double precision,
  required_precision double precision not null,minimum_kappa double precision not null,benchmark_pass boolean not null default false,
  failure_reason text,created_at timestamptz not null default now()
);