\set ON_ERROR_STOP on

do $$
declare
  v_exp bigint;
  v_eval timestamptz;
  v_rows integer;
  v_bad integer;
begin
  select id,(metrics->'economic_capture_evidence'->>'evaluation_as_of')::timestamptz
    into v_exp,v_eval
  from public.oracle_v6_experiments
  where model_family='COUNT_NULL_MODEL'
    and model_version='FORMAL_COUNT_NULL_V1'
    and invalidated_at is null
    and metrics ? 'economic_capture_evidence'
  order by created_at desc,id desc limit 1;
  if v_exp is null or v_eval is null then raise exception 'V6 ECONOMIC CAPTURE FAIL: no summary'; end if;
  select count(*) into v_rows from public.oracle_v6_economic_capture_evidence
   where experiment_id=v_exp and evaluation_as_of=v_eval and model_version='ECONOMIC_CAPTURE_EVIDENCE_V1';
  if v_rows<1 then raise exception 'V6 ECONOMIC CAPTURE FAIL: no tension supplier rows'; end if;
  select count(*) into v_bad from public.oracle_v6_economic_capture_evidence
   where experiment_id=v_exp and evaluation_as_of=v_eval and model_version='ECONOMIC_CAPTURE_EVIDENCE_V1'
     and (not supplier_role_confirmed or pricing_power_evidence or coalesce((metadata->>'probability_synthesized')::boolean,true));
  if v_bad<>0 then raise exception 'V6 ECONOMIC CAPTURE FAIL: invalid descriptive rows %',v_bad; end if;
end $$;

select metrics->'economic_capture_evidence' as economic_capture_evidence
from public.oracle_v6_experiments
where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null
order by created_at desc,id desc limit 1;
