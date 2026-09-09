\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_eval timestamptz;
  v_upgraded integer;
  v_bad integer;
begin
  select id,(metrics->'bottleneck_tension'->>'evaluation_as_of')::timestamptz
    into v_exp,v_eval
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
    and metrics ? 'bottleneck_tension'
  order by created_at desc,id desc limit 1;
  if v_exp is null or v_eval is null then
    raise exception 'V6 BOTTLENECK TENSION FAIL: no summary';
  end if;
  select count(*) into v_upgraded
  from public.oracle_v6_structural_bottlenecks
  where experiment_id=v_exp and evaluation_as_of=v_eval and structural_status='EVIDENCE_BACKED_TENSION';
  if v_upgraded<1 then
    raise exception 'V6 BOTTLENECK TENSION FAIL: no upgraded bottleneck';
  end if;
  select count(*) into v_bad
  from public.oracle_v6_structural_bottlenecks
  where experiment_id=v_exp and evaluation_as_of=v_eval and structural_status='EVIDENCE_BACKED_TENSION'
    and (independent_source_count<2 or forecast_probability is not null
         or coalesce((metadata->>'hard_tension_count')::int,0)<1
         or coalesce((metadata->>'probability_synthesized')::boolean,true));
  if v_bad<>0 then
    raise exception 'V6 BOTTLENECK TENSION FAIL: invalid upgraded rows %',v_bad;
  end if;
end $$;

select metrics->'bottleneck_tension' as bottleneck_tension
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null
order by created_at desc,id desc limit 1;
