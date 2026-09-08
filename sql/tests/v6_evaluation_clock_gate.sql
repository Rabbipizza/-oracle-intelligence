\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_signal timestamptz;
  v_eval timestamptz;
  v_bad integer;
begin
  select id,(metrics->>'decision_as_of')::timestamptz
    into v_exp,v_signal
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
  order by created_at desc,id desc limit 1;

  select evaluation_as_of into v_eval
  from public.oracle_v6_evaluation_runs
  where experiment_id=v_exp
  order by evaluation_as_of desc,id desc limit 1;

  if v_exp is null or v_signal is null or v_eval is null then
    raise exception 'V6 EVALUATION CLOCK FAIL: missing experiment/signal/evaluation timestamp';
  end if;

  if v_eval < v_signal then
    raise exception 'V6 EVALUATION CLOCK FAIL: evaluation % precedes signal availability %',v_eval,v_signal;
  end if;

  select count(*) into v_bad
  from public.oracle_v6_evaluation_runs
  where experiment_id=v_exp and evaluation_as_of < signal_available_at;
  if v_bad<>0 then
    raise exception 'V6 EVALUATION CLOCK FAIL: % evaluation rows precede signal availability',v_bad;
  end if;
end $$;

select id,experiment_id,external_run_id,signal_available_at,evaluation_as_of
from public.oracle_v6_evaluation_runs
order by evaluation_as_of desc,id desc limit 5;
