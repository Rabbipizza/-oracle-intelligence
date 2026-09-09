\set ON_ERROR_STOP on

do $$
declare
  v_model text := 'FORWARD_VALIDATION_V1';
  v_signals integer;
  v_watch integer;
  v_buy integer;
  v_missing_shells integer;
  v_bad_maturity integer;
begin
  select count(*),
         count(*) filter(where decision='WATCH'),
         count(*) filter(where decision in ('BUY_CANDIDATE','PILOT_BUY'))
    into v_signals,v_watch,v_buy
  from public.oracle_v6_forward_signals
  where model_version=v_model;

  if v_signals<1 then
    raise exception 'V6 FORWARD VALIDATION FAIL: no immutable production signals';
  end if;
  if v_watch<1 then
    raise exception 'V6 FORWARD VALIDATION FAIL: no WATCH signal captured';
  end if;
  if v_buy<>0 then
    raise exception 'V6 FORWARD VALIDATION FAIL: unvalidated BUY signal captured %',v_buy;
  end if;

  select count(*) into v_missing_shells
  from public.oracle_v6_forward_signals s
  where s.model_version=v_model
    and (select count(*) from public.oracle_v6_forward_outcomes o where o.signal_id=s.id and o.horizon_months in (3,6,12,24))<>4;
  if v_missing_shells<>0 then
    raise exception 'V6 FORWARD VALIDATION FAIL: % signals missing 3/6/12/24m outcome shells',v_missing_shells;
  end if;

  select count(*) into v_bad_maturity
  from public.oracle_v6_forward_outcomes o
  join public.oracle_v6_forward_signals s on s.id=o.signal_id
  where s.model_version=v_model
    and o.matured_at is not null
    and o.target_month > date_trunc('month',current_date)::date;
  if v_bad_maturity<>0 then
    raise exception 'V6 FORWARD VALIDATION FAIL: % future outcomes matured early',v_bad_maturity;
  end if;
end $$;

select metrics->'forward_validation' as forward_validation
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null
order by created_at desc,id desc limit 1;
