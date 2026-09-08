-- ORACLE V6 P0-5: point-in-time historical listed universe.
-- Production data lives in oracle_v6_historical_listings.
-- This file versions the read/gate semantics and deliberately does not invent
-- listing dates or corporate actions.

create or replace function public.oracle_v6_universe_as_of(p_date date)
returns table(
  ticker text,
  legal_name text,
  cik text,
  exchange text,
  instrument_type text,
  valid_from date,
  valid_to date,
  listing_status text,
  source_quality text,
  source text,
  source_ref text,
  metadata jsonb
)
language sql
stable
set search_path=public
as $$
  with eligible as (
    select h.*,
           row_number() over (
             partition by h.ticker
             order by case h.source_quality when 'PRIMARY' then 3 when 'SECONDARY' then 2 else 1 end desc,
                      h.valid_from desc,
                      h.id desc
           ) as rn
    from public.oracle_v6_historical_listings h
    where h.valid_from <= p_date
      and (h.valid_to is null or h.valid_to >= p_date)
  )
  select ticker,legal_name,cik,exchange,instrument_type,valid_from,valid_to,
         listing_status,source_quality,source,source_ref,metadata
  from eligible
  where rn=1;
$$;

create or replace view public.oracle_v6_universe_coverage as
select
  count(*) as historical_rows,
  count(distinct ticker) as distinct_tickers,
  min(valid_from) as coverage_start,
  max(coalesce(valid_to,current_date)) as coverage_end,
  count(*) filter (where lifecycle_event like '%DELISTING') as delisting_rows,
  count(*) filter (where lifecycle_event like 'TICKER_CHANGE%') as ticker_change_rows,
  count(*) filter (where lifecycle_event like '%MERGER%') as merger_rows,
  count(*) filter (where source_quality='PRIMARY') as primary_rows,
  count(*) filter (where source_quality='INFERRED') as inferred_rows,
  (
    count(*) filter (where lifecycle_event like '%DELISTING' and source_quality in ('PRIMARY','SECONDARY')) > 0
    and count(*) filter (where lifecycle_event like 'TICKER_CHANGE%' and source_quality in ('PRIMARY','SECONDARY')) > 0
    and count(*) filter (where lifecycle_event like '%MERGER%' and source_quality in ('PRIMARY','SECONDARY')) > 0
  ) as survivorship_safe
from public.oracle_v6_historical_listings;

create or replace view public.oracle_v6_universe_gate as
select
  c.*,
  (select count(*) from public.oracle_v5_universe) as current_universe_rows,
  (select count(*) from public.oracle_v5_universe u where exists (
      select 1 from public.oracle_v6_historical_listings h where h.ticker=u.ticker
  )) as current_universe_covered,
  (c.delisting_rows > 0 and c.ticker_change_rows > 0 and c.merger_rows > 0) as lifecycle_classes_covered,
  false as exhaustive_market_delisting_coverage,
  'P0-5 implements point-in-time historical membership and verified dead/ticker-change/merger cases. Full US-market delisting census still requires a bulk delisting feed.'::text as scope_note
from public.oracle_v6_universe_coverage c;
