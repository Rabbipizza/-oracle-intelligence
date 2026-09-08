create table if not exists public.oracle_v6_sec_position_facts (
  id bigserial primary key,
  ticker text not null,
  cik text not null,
  taxonomy text not null,
  concept text not null,
  unit text not null,
  period_end date not null,
  filed_date date not null,
  available_at timestamptz not null,
  accession text,
  form text,
  fiscal_year integer,
  fiscal_period text,
  value numeric not null,
  source_url text not null,
  availability_quality text not null default 'ESTIMATED_CONSERVATIVE_FROM_FILED_DATE',
  ingested_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  constraint oracle_v6_sec_position_facts_avail_check check (available_at >= filed_date::timestamptz)
);
create unique index if not exists oracle_v6_sec_position_facts_uq
  on public.oracle_v6_sec_position_facts(ticker,taxonomy,concept,period_end,filed_date,coalesce(accession,''),value);
create index if not exists oracle_v6_sec_position_facts_pit_idx
  on public.oracle_v6_sec_position_facts(ticker,available_at,period_end desc);

create table if not exists public.oracle_v6_position_snapshots (
  id bigserial primary key,
  ticker text not null,
  as_of timestamptz not null,
  fiscal_period_end date not null,
  shares_outstanding numeric not null,
  cash numeric not null,
  debt numeric not null,
  source_components jsonb not null default '[]'::jsonb,
  source_quality text not null,
  model_version text not null default 'SEC_POSITION_V1',
  metadata jsonb not null default '{}'::jsonb
);
create unique index if not exists oracle_v6_position_snapshots_uq
  on public.oracle_v6_position_snapshots(ticker,as_of,fiscal_period_end,model_version);
create index if not exists oracle_v6_position_snapshots_pit_idx
  on public.oracle_v6_position_snapshots(ticker,as_of desc);

alter table public.oracle_v6_sec_position_facts enable row level security;
alter table public.oracle_v6_position_snapshots enable row level security;
