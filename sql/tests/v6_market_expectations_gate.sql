\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_state text;
  v_rows integer;
begin
  select id,metrics->'market_expectations_gate'->>'state'
    into v_exp,v_state
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
    and metrics ? 'market_expectations_gate'
  order by created_at desc,id desc limit 1;

  if v_exp is null then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: no gate summary';
  end if;

  select count(*) into v_rows
  from public.oracle_v6_market_expectations
  where model_version='MARKET_EXPECTATIONS_GATE_V1';

  if v_state='NO_EXPECTATION_MODEL_MISSING_FCF_INPUTS' and v_rows<>0 then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: reverse-DCF rows exist despite missing FCF inputs';
  end if;

  if v_state not in ('NO_EXPECTATION_MODEL_MISSING_FCF_INPUTS','INPUT_SCHEMA_PRESENT_REQUIRES_MODEL_IMPLEMENTATION') then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: unexpected state %',v_state;
  end if;
end $$;

select metrics->'market_expectations_gate' as market_expectations_gate
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL'
  and model_version='FORMAL_COUNT_NULL_V1'
  and invalidated_at is null
order by created_at desc,id desc limit 1;
