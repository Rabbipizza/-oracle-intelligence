\set ON_ERROR_STOP on

do $$
declare
  exp_id bigint;
  decision_as_of timestamptz;
  test_week date;
  bad_null_rows integer;
  bad_trend_rows integer;
  old_backdated_null_rows integer;
  old_backdated_trend_rows integer;
begin
  select e.id,
         (e.metrics->>'decision_as_of')::timestamptz,
         (e.metrics->>'test_week')::date
    into exp_id, decision_as_of, test_week
  from public.oracle_v6_experiments e
  where e.model_family='COUNT_NULL_MODEL'
    and e.model_version='FORMAL_COUNT_NULL_V1'
    and e.invalidated_at is null
  order by e.created_at desc,e.id desc
  limit 1;

  if exp_id is null or decision_as_of is null or test_week is null then
    raise exception 'V6 Discovery PIT FAIL: experiment/test_week/decision_as_of missing';
  end if;

  if decision_as_of <= test_week::timestamptz then
    raise exception 'V6 Discovery PIT FAIL: decision_as_of % is not later than test_week %', decision_as_of, test_week;
  end if;

  select count(*) into bad_null_rows
  from public.oracle_v6_signal_null_models n
  where n.model_version='FORMAL_COUNT_NULL_V1'
    and n.training_window->>'test_week'=test_week::text
    and n.as_of <> decision_as_of;

  if bad_null_rows <> 0 then
    raise exception 'V6 Discovery PIT FAIL: % formal null rows have wrong as_of', bad_null_rows;
  end if;

  select count(*) into old_backdated_null_rows
  from public.oracle_v6_signal_null_models n
  where n.model_version='FORMAL_COUNT_NULL_V1'
    and n.training_window->>'test_week'=test_week::text
    and n.as_of = test_week::timestamptz;

  if old_backdated_null_rows <> 0 then
    raise exception 'V6 Discovery PIT FAIL: % backdated formal null rows remain', old_backdated_null_rows;
  end if;

  select count(*) into bad_trend_rows
  from public.oracle_v6_trend_probabilities t
  where t.experiment_id=exp_id
    and t.model_version='TREND_PERSISTENCE_V1'
    and t.as_of <> decision_as_of;

  if bad_trend_rows <> 0 then
    raise exception 'V6 Discovery PIT FAIL: % trend rows have wrong as_of', bad_trend_rows;
  end if;

  select count(*) into old_backdated_trend_rows
  from public.oracle_v6_trend_probabilities t
  where t.experiment_id=exp_id
    and t.model_version='TREND_PERSISTENCE_V1'
    and t.as_of = test_week::timestamptz;

  if old_backdated_trend_rows <> 0 then
    raise exception 'V6 Discovery PIT FAIL: % backdated trend rows remain', old_backdated_trend_rows;
  end if;
end $$;

select e.id,e.metrics->>'test_week' as test_week,e.metrics->>'decision_as_of' as decision_as_of,
       e.metrics->'fdr' as fdr,e.metrics->'trend_probability' as trend_probability
from public.oracle_v6_experiments e
where e.model_family='COUNT_NULL_MODEL' and e.model_version='FORMAL_COUNT_NULL_V1'
order by e.created_at desc,e.id desc limit 1;
