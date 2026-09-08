\set ON_ERROR_STOP on

do $$
declare
  v_bad_available integer;
  v_bad_snapshot integer;
  v_rows integer;
  v_tickers integer;
begin
  select count(*) into v_bad_available
  from public.oracle_v6_sec_position_facts
  where available_at < filed_date::timestamptz;

  select count(*) into v_bad_snapshot
  from public.oracle_v6_position_snapshots
  where model_version='SEC_POSITION_V1'
    and (shares_outstanding<=0 or cash<0 or debt<0 or as_of is null);

  select count(*),count(distinct ticker)
    into v_rows,v_tickers
  from public.oracle_v6_position_snapshots
  where model_version='SEC_POSITION_V1';

  if v_bad_available<>0 then
    raise exception 'V6 SEC POSITION PIT FAIL: % facts precede filed date',v_bad_available;
  end if;
  if v_bad_snapshot<>0 then
    raise exception 'V6 SEC POSITION FAIL: % invalid snapshots',v_bad_snapshot;
  end if;
  if v_rows=0 or v_tickers=0 then
    raise exception 'V6 SEC POSITION FAIL: no complete position snapshots';
  end if;
end $$;

select count(*) facts,count(distinct ticker) tickers
from public.oracle_v6_sec_position_facts;
select count(*) snapshots,count(distinct ticker) tickers
from public.oracle_v6_position_snapshots
where model_version='SEC_POSITION_V1';
