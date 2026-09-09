\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_state text;
  v_gate_rows integer;
  v_reverse_rows integer;
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

  select count(*) into v_gate_rows
  from public.oracle_v6_market_expectations
  where model_version='MARKET_EXPECTATIONS_GATE_V1';
  if v_gate_rows<>0 then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: prerequisite gate wrote valuation rows';
  end if;

  select count(*) into v_reverse_rows
  from public.oracle_v6_market_expectations
  where model_version='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1'
    and as_of=(select max(evaluation_as_of) from public.oracle_v6_evaluation_runs where experiment_id=v_exp);

  if v_state not in ('NO_EXPECTATION_MODEL_MISSING_PIT_FCF_INPUTS','PIT_FCF_AVAILABLE_REVERSE_DCF_INCOMPLETE','REVERSE_DCF_AVAILABLE_NO_CALIBRATED_FORWARD_EXPECTATION_GAP') then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: unexpected state %',v_state;
  end if;

  if v_reverse_rows>0 and v_state<>'REVERSE_DCF_AVAILABLE_NO_CALIBRATED_FORWARD_EXPECTATION_GAP' then
    raise exception 'V6 MARKET EXPECTATIONS FAIL: reverse DCF exists but gate state is %',v_state;
  end if;
end $$;

select metrics->'market_expectations_gate' as market_expectations_gate
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL'
  and model_version='FORMAL_COUNT_NULL_V1'
  and invalidated_at is null
order by created_at desc,id desc limit 1;
