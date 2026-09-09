\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_eval timestamptz;
  v_model text;
  v_rows integer;
  v_bad integer;
begin
  select id,
         (metrics->'economic_capture_evidence'->>'evaluation_as_of')::timestamptz,
         metrics->'economic_capture_evidence'->>'model_version'
    into v_exp,v_eval,v_model
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
    and metrics ? 'economic_capture_evidence'
  order by created_at desc,id desc limit 1;

  if v_exp is null or v_eval is null or v_model is null then
    raise exception 'V6 ECONOMIC CAPTURE FAIL: no current summary/model';
  end if;

  select count(*) into v_rows
  from public.oracle_v6_economic_capture_evidence
  where experiment_id=v_exp and evaluation_as_of=v_eval and model_version=v_model;
  if v_rows<1 then
    raise exception 'V6 ECONOMIC CAPTURE FAIL: no tension supplier rows for %',v_model;
  end if;

  select count(*) into v_bad
  from public.oracle_v6_economic_capture_evidence
  where experiment_id=v_exp and evaluation_as_of=v_eval and model_version=v_model
    and (
      not supplier_role_confirmed
      or coalesce((metadata->>'probability_synthesized')::boolean,true)
    );
  if v_bad<>0 then
    raise exception 'V6 ECONOMIC CAPTURE FAIL: invalid descriptive rows %',v_bad;
  end if;

  -- Pricing evidence is valid descriptive evidence in V2; it must never be
  -- confused with a calibrated pricing-power probability.
  if coalesce((
      select metrics->'economic_capture_evidence'->>'pricing_power_probabilities_written'
      from public.oracle_v6_experiments where id=v_exp
    )::int,0) <> 0 then
    raise exception 'V6 ECONOMIC CAPTURE FAIL: uncalibrated pricing probability written';
  end if;
end $$;

select metrics->'economic_capture_evidence' as economic_capture_evidence
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null
order by created_at desc,id desc limit 1;
