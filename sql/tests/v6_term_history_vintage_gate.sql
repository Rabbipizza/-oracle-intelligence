\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_week date;
  v_available timestamptz;
  v_null_bad integer;
  v_fdr_bad integer;
  v_trend_bad integer;
  v_metric timestamptz;
begin
  select e.id,(e.metrics->>'test_week')::date
    into v_exp,v_week
  from public.oracle_v6_experiments e
  where e.model_family='COUNT_NULL_MODEL'
    and e.model_version='FORMAL_COUNT_NULL_V1'
    and e.invalidated_at is null
    and e.metrics ? 'test_week'
  order by e.created_at desc,e.id desc limit 1;

  if v_exp is null then
    raise exception 'V6 VINTAGE FAIL: no formal experiment';
  end if;

  select available_at into v_available
  from public.oracle_v6_term_history_vintages
  where week_start=v_week;

  if v_available is null then
    raise exception 'V6 VINTAGE FAIL: no vintage for %',v_week;
  end if;

  select count(*) into v_null_bad
  from public.oracle_v6_signal_null_models n
  where n.model_version='FORMAL_COUNT_NULL_V1'
    and n.training_window->>'test_week'=v_week::text
    and n.as_of<>v_available;

  select count(*) into v_fdr_bad
  from public.oracle_v6_multiple_testing m
  where m.experiment_id=v_exp
    and m.method='BENJAMINI_HOCHBERG'
    and m.as_of<>v_available;

  select count(*) into v_trend_bad
  from public.oracle_v6_trend_probabilities t
  where t.experiment_id=v_exp
    and t.model_version='TREND_PERSISTENCE_V1'
    and t.as_of<>v_available;

  select (metrics->>'decision_as_of')::timestamptz into v_metric
  from public.oracle_v6_experiments where id=v_exp;

  if v_null_bad<>0 then raise exception 'V6 VINTAGE FAIL: % null rows mismatch',v_null_bad; end if;
  if v_fdr_bad<>0 then raise exception 'V6 VINTAGE FAIL: % FDR rows mismatch',v_fdr_bad; end if;
  if v_trend_bad<>0 then raise exception 'V6 VINTAGE FAIL: % trend rows mismatch',v_trend_bad; end if;
  if v_metric is distinct from v_available then
    raise exception 'V6 VINTAGE FAIL: experiment metric % != vintage %',v_metric,v_available;
  end if;
end $$;

select week_start,last_event_date,available_at,availability_quality,provenance
from public.oracle_v6_term_history_vintages
order by week_start desc limit 5;
