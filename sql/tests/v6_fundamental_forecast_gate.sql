\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_status text;
  v_probs integer;
  v_rows integer;
  v_holdout integer;
begin
  select id,metrics->'fundamental_forecast'->>'calibration_status',
         coalesce((metrics->'fundamental_forecast'->'holdout'->>'n')::integer,0)
    into v_exp,v_status,v_holdout
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
    and metrics ? 'fundamental_forecast'
  order by created_at desc,id desc limit 1;
  if v_exp is null then raise exception 'V6 FUNDAMENTAL FORECAST FAIL: no summary'; end if;

  select count(*),count(*) filter(where p_exceed_implied is not null)
    into v_rows,v_probs
  from public.oracle_v6_fundamental_forecasts
  where experiment_id=v_exp and model_version='FCF5Y_RIDGE_PIT_V1'
    and as_of=(select max(evaluation_as_of) from public.oracle_v6_evaluation_runs where experiment_id=v_exp);

  if v_status='CALIBRATED_HOLDOUT_PASS' then
    if v_holdout<40 then raise exception 'V6 FUNDAMENTAL FORECAST FAIL: calibrated with only % holdout rows',v_holdout; end if;
    if v_probs=0 then raise exception 'V6 FUNDAMENTAL FORECAST FAIL: calibrated but no probabilities written'; end if;
  else
    if v_probs<>0 then raise exception 'V6 FUNDAMENTAL FORECAST FAIL: uncalibrated model wrote % probabilities',v_probs; end if;
  end if;
end $$;

select metrics->'fundamental_forecast' as fundamental_forecast
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null
order by created_at desc,id desc limit 1;
