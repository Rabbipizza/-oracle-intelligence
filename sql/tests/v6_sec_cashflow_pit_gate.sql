\set ON_ERROR_STOP on

do $$
declare
  v_bad_available integer;
  v_bad_fcf integer;
  v_snapshots integer;
  v_tickers integer;
begin
  select count(*) into v_bad_available
  from public.oracle_v6_sec_cashflow_facts
  where available_at < filed_date::timestamptz;

  select count(*) into v_bad_fcf
  from public.oracle_v6_fcf_snapshots
  where model_version='SEC_FCF_ANNUAL_V1'
    and free_cash_flow <> operating_cash_flow - capex;

  select count(*),count(distinct ticker)
    into v_snapshots,v_tickers
  from public.oracle_v6_fcf_snapshots
  where model_version='SEC_FCF_ANNUAL_V1';

  if v_bad_available<>0 then
    raise exception 'V6 SEC CASHFLOW PIT FAIL: % facts available before filed date',v_bad_available;
  end if;
  if v_bad_fcf<>0 then
    raise exception 'V6 SEC FCF FAIL: % snapshots violate CFO-capex identity',v_bad_fcf;
  end if;
  if v_snapshots=0 or v_tickers=0 then
    raise exception 'V6 SEC FCF FAIL: no annual FCF snapshots materialized';
  end if;
end $$;

select count(*) facts,count(distinct ticker) fact_tickers,
       min(available_at) min_available_at,max(available_at) max_available_at
from public.oracle_v6_sec_cashflow_facts;

select count(*) snapshots,count(distinct ticker) tickers,
       min(as_of) min_as_of,max(as_of) max_as_of
from public.oracle_v6_fcf_snapshots
where model_version='SEC_FCF_ANNUAL_V1';
